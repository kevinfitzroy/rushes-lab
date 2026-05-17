"""审批 IM 卡片推送服务 — iter7 权限审批卡片。

入口:
- notify_pending(approval, ...) — POST /approvals 后,给 target admin 推审批卡
- notify_decided(approval, ...) — approve/reject 后,给申请者推结果通知卡

设计:
- 失败 best-effort(log + audit warning,不影响主流程)
- 卡片 message_id 写入 approval.granted_tuple_ref['_notify'] —— iter 后续 update 卡片用
  (避免单独 migration;若以后需独立字段再加)
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import Request

from app.db.tables import ApprovalRequest, Asset, Folder, Project, User
from app.services.approval_service import (
    ApprovalDecisionError,
    DecisionContext,
    decide,
)
from app.services.audit import AuditService
from app.services.feishu_card_handlers import register_card_action
from app.services.feishu_cards import (
    build_approval_card,
    build_approval_decided_card,
)
from app.services.feishu_client import FeishuAPIError, FeishuClient
from app.services.permissions import PermissionsService
from app.settings import Settings, get_settings

log = logging.getLogger(__name__)


# ─── 主入口 ───────────────────────────────────────────────────────────────────
async def notify_pending(
    *,
    approval_id: uuid.UUID,
    db: AsyncSession,
    feishu: FeishuClient,
    permissions: PermissionsService,
    audit: AuditService,
    settings: Settings,
) -> None:
    """给 target admin 推待审卡 — BackgroundTask 调用,失败仅 log。"""
    if not settings.feishu_im_enabled:
        return

    approval = await db.get(ApprovalRequest, approval_id)
    if approval is None:
        log.warning("notify_pending: approval %s not found", approval_id)
        return

    target_label, _project_id = await _resolve_target(db, approval)
    action_label = _action_label(approval)
    applicant = await db.get(User, approval.applicant_user_id)
    applicant_name = applicant.name if applicant else "未知"

    admin_open_ids = await _admin_open_ids_for_target(db, permissions, approval)
    if not admin_open_ids:
        log.warning("notify_pending: no admin feishu_open_id for approval %s target=%s:%s",
                    approval_id, approval.target_type, approval.target_id)
        return

    web_url = _web_url(settings, "approvals", str(approval.id))
    card = build_approval_card(
        applicant_name=applicant_name,
        target_label=target_label,
        action_label=action_label,
        reason=approval.reason,
        approval_id=str(approval.id),
        web_url=web_url,
    )

    sent: list[dict[str, Any]] = []
    for open_id in admin_open_ids:
        try:
            data = await feishu.send_im_card(open_id, card, receive_id_type="open_id")
            sent.append({"open_id": open_id, "message_id": data.get("message_id")})
        except FeishuAPIError as e:
            log.warning("notify_pending feishu send fail approval=%s open_id=%s code=%s msg=%s",
                        approval_id, open_id, e.code, e.msg)
            sent.append({"open_id": open_id, "error": f"{e.code}:{e.msg[:120]}"})
        except Exception as e:  # noqa: BLE001
            log.warning("notify_pending unexpected fail approval=%s open_id=%s err=%s",
                        approval_id, open_id, e)
            sent.append({"open_id": open_id, "error": str(e)[:120]})

    # 把 message_id 列表 merge 进 granted_tuple_ref(JSONB)— 暂存,iter 后续 update 卡用
    if sent:
        existing = dict(approval.granted_tuple_ref or {})
        existing["_notify"] = {"pending_sent": sent}
        approval.granted_tuple_ref = existing
        await db.commit()

    await audit.write(
        event_type="approval_notified",
        actor_user_id=None,
        details={
            "approval_id": str(approval.id),
            "phase": "pending",
            "recipients": sent,
        },
    )
    log.info("notify_pending approval=%s recipients=%d", approval_id, len(sent))


async def notify_decided(
    *,
    approval_id: uuid.UUID,
    db: AsyncSession,
    feishu: FeishuClient,
    audit: AuditService,
    settings: Settings,
) -> None:
    """给申请者推决定结果卡(approve/reject 后)— best-effort。"""
    if not settings.feishu_im_enabled:
        return

    approval = await db.get(ApprovalRequest, approval_id)
    if approval is None or approval.status not in ("approved", "rejected"):
        return

    applicant = await db.get(User, approval.applicant_user_id)
    if applicant is None or not applicant.feishu_open_id:
        log.warning("notify_decided: applicant has no feishu_open_id approval=%s", approval_id)
        return

    decider = (
        await db.get(User, approval.approver_user_id) if approval.approver_user_id else None
    )
    target_label, _ = await _resolve_target(db, approval)

    card = build_approval_decided_card(
        applicant_name=applicant.name,
        target_label=target_label,
        action_label=_action_label(approval),
        decision="approve" if approval.status == "approved" else "reject",
        decided_by_name=decider.name if decider else "(系统)",
        decision_note=approval.decision_note,
        approval_id=str(approval.id),
    )

    try:
        data = await feishu.send_im_card(
            applicant.feishu_open_id, card, receive_id_type="open_id"
        )
        message_id = data.get("message_id")
    except FeishuAPIError as e:
        log.warning("notify_decided feishu fail approval=%s code=%s msg=%s",
                    approval_id, e.code, e.msg)
        message_id = None
    except Exception as e:  # noqa: BLE001
        log.warning("notify_decided unexpected fail approval=%s err=%s", approval_id, e)
        message_id = None

    await audit.write(
        event_type="approval_notified",
        actor_user_id=approval.approver_user_id,
        details={
            "approval_id": str(approval.id),
            "phase": "decided",
            "decision": approval.status,
            "recipient_open_id": applicant.feishu_open_id,
            "message_id": message_id,
        },
    )


# ─── helpers ──────────────────────────────────────────────────────────────────
async def _resolve_target(
    db: AsyncSession, approval: ApprovalRequest
) -> tuple[str, uuid.UUID | None]:
    """返 (display_label, project_id_for_audit)。"""
    if approval.target_type == "asset":
        asset = await db.get(Asset, approval.target_id)
        if asset is None:
            return f"asset:{approval.target_id}", None
        folder = await db.get(Folder, asset.folder_id)
        if folder is None:
            return asset.filename, None
        project = await db.get(Project, folder.project_id)
        return f"{project.name if project else '?'} / {folder.name} / {asset.filename}", \
               folder.project_id

    if approval.target_type in ("sensitive_folder", "folder"):
        folder = await db.get(Folder, approval.target_id)
        if folder is None:
            return f"folder:{approval.target_id}", None
        project = await db.get(Project, folder.project_id)
        return f"{project.name if project else '?'} / {folder.name}", folder.project_id

    if approval.target_type == "project":
        project = await db.get(Project, approval.target_id)
        return (project.name if project else f"project:{approval.target_id}"), approval.target_id

    return f"{approval.target_type}:{approval.target_id}", None


def _action_label(approval: ApprovalRequest) -> str:
    dur = approval.duration_seconds
    dur_label = _duration_label(dur) if dur else None
    if approval.action == "download":
        return f"临时下载 {dur_label}" if dur_label else "临时下载"
    if approval.action == "access":
        return f"临时邀请加入 {dur_label}" if dur_label else "永久邀请加入"
    return approval.action


def _duration_label(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} 秒"
    if seconds < 3600:
        return f"{seconds // 60} 分钟"
    if seconds < 86400:
        h = seconds / 3600
        return f"{int(h)} 小时" if h.is_integer() else f"{h:.1f} 小时"
    d = seconds / 86400
    return f"{int(d)} 天" if d.is_integer() else f"{d:.1f} 天"


async def _admin_open_ids_for_target(
    db: AsyncSession,
    permissions: PermissionsService,
    approval: ApprovalRequest,
) -> list[str]:
    """找 target 的 admin → 飞书 open_id 列表(去 inactive / 无 open_id 的)。"""
    object_type = approval.target_type
    object_id = str(approval.target_id)
    # v4 model:OpenFGA list_users 返 user:<open_id> 列表,可直接用作 open_id
    open_ids = await permissions.list_users_with_relation(
        object_type=object_type, object_id=object_id, relation="can_admin"
    )
    if not open_ids:
        return []
    # 仅返还 db 中 is_active=True 的 user 对应 open_id(避免推给已离职)
    stmt = select(User.feishu_open_id).where(
        User.feishu_open_id.in_(open_ids), User.is_active.is_(True),
    )
    res = await db.execute(stmt)
    return [row[0] for row in res.all() if row[0]]


def _web_url(settings: Settings, *parts: str) -> str:
    base = settings.web_app_base_url.rstrip("/") + "/"
    return base + "/".join(p.strip("/") for p in parts)


# ─── BackgroundTask wrappers ──────────────────────────────────────────────────
async def run_notify_pending_bg(
    *,
    approval_id: uuid.UUID,
    feishu: FeishuClient,
    permissions: PermissionsService,
    settings: Settings,
) -> None:
    """FastAPI BackgroundTasks 入口 — 自开 db session,失败仅 log。"""
    from app.db.session import get_sessionmaker
    try:
        async with get_sessionmaker()() as db:
            audit = AuditService(db)
            await notify_pending(
                approval_id=approval_id, db=db, feishu=feishu,
                permissions=permissions, audit=audit, settings=settings,
            )
    except Exception:  # noqa: BLE001
        log.exception("run_notify_pending_bg failed approval=%s", approval_id)


async def run_notify_decided_bg(
    *,
    approval_id: uuid.UUID,
    feishu: FeishuClient,
    settings: Settings,
) -> None:
    from app.db.session import get_sessionmaker
    try:
        async with get_sessionmaker()() as db:
            audit = AuditService(db)
            await notify_decided(
                approval_id=approval_id, db=db, feishu=feishu,
                audit=audit, settings=settings,
            )
    except Exception:  # noqa: BLE001
        log.exception("run_notify_decided_bg failed approval=%s", approval_id)


# ─── 飞书卡片回调:approval_decision ──────────────────────────────────────────
@register_card_action("approval_decision")
async def handle_approval_decision(
    event: dict[str, Any], request: Request
) -> dict[str, Any] | None:
    """卡片"通过 / 拒绝"按钮点击 — 由 webhooks.feishu/card.action.trigger 路由到此。

    event.action.value 约定:
      {"intent": "approval_decision", "approval_id": "<uuid>", "decision": "approve|reject"}

    返 {"toast": {...}} — 飞书侧弹个 toast 给点击者;iter 后续可加 "card" 字段做卡片同步 update。
    """
    from app.db.session import get_sessionmaker

    value = (event.get("action") or {}).get("value") or {}
    approval_id_str = value.get("approval_id")
    decision = value.get("decision")
    if not approval_id_str or decision not in ("approve", "reject"):
        return {"toast": {"type": "error", "content": "卡片数据缺失或无效"}}
    try:
        approval_id = uuid.UUID(approval_id_str)
    except ValueError:
        return {"toast": {"type": "error", "content": f"非法 approval_id: {approval_id_str}"}}

    operator = event.get("operator") or {}
    op_open_id = operator.get("open_id")
    if not op_open_id:
        return {"toast": {"type": "error", "content": "缺 operator.open_id"}}

    feishu: FeishuClient = request.app.state.feishu_client
    permissions: PermissionsService = request.app.state.permissions
    settings = get_settings()

    async with get_sessionmaker()() as db:
        # 1) operator open_id → internal user_id
        u_stmt = select(User).where(User.feishu_open_id == op_open_id)
        u_res = await db.execute(u_stmt)
        operator_user = u_res.scalar_one_or_none()
        if operator_user is None:
            log.warning("approval_decision: unknown operator open_id=%s", op_open_id)
            return {"toast": {"type": "error", "content": "你尚未登录过本应用 — 请先在 web 端登录一次"}}

        audit = AuditService(db)
        try:
            approval = await decide(
                db=db,
                approval_id=approval_id,
                decider_user_id=operator_user.id,
                decider_open_id=op_open_id,
                decision=decision,  # type: ignore[arg-type]
                decision_note="(via 飞书 IM 卡片)",
                permissions=permissions,
                audit=audit,
                ctx=DecisionContext(),
            )
        except ApprovalDecisionError as e:
            log.info("approval_decision rejected by service status=%s msg=%s",
                     e.status_code, e.message)
            return {"toast": {"type": "warning", "content": e.message}}

    # 2) 异步给申请者推决定结果卡(同样独立 db session)
    await run_notify_decided_bg(
        approval_id=approval.id, feishu=feishu, settings=settings,
    )

    label = "已通过" if decision == "approve" else "已拒绝"
    return {"toast": {"type": "success", "content": f"审批{label}"}}
