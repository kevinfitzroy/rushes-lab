"""审批决策核心服务 — iter a1 适配 v4 OpenFGA model(subject 用飞书 ID)。

decide 入口两个:
  1. HTTP:POST /api/v1/approvals/{id}/approve|reject — router endpoint
  2. 飞书卡片回调:card.action.trigger value.intent='approval_decision' — feishu_card_handlers
两个入口都调本服务,共用 admin check + grant 写入 + 落库 + audit 逻辑。
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.tables import ApprovalRequest, User
from app.services.audit import AuditService
from app.services.permissions import PermissionsService

log = logging.getLogger(__name__)


class ApprovalDecisionError(Exception):
    """业务校验失败:对应 HTTP 4xx;router/handler 自行映射。"""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


@dataclass
class DecisionContext:
    request_ip: str | None = None
    user_agent: str | None = None


async def fetch_pending(db: AsyncSession, approval_id: uuid.UUID) -> ApprovalRequest:
    approval = await db.get(ApprovalRequest, approval_id)
    if not approval:
        raise ApprovalDecisionError(404, "approval not found")
    if approval.status != "pending":
        raise ApprovalDecisionError(409, f"approval already {approval.status}")
    return approval


async def enforce_admin_for_target(
    permissions: PermissionsService,
    decider_user_id: uuid.UUID,
    decider_open_id: str,
    approval: ApprovalRequest,
    *,
    audit: AuditService | None = None,
    ctx: DecisionContext | None = None,
    is_system_admin: bool = False,
) -> None:
    """user 必须对申请目标 can_admin(v4 model:asset/folder/sensitive_folder/project 都用 can_admin);system admin 直通。"""
    if is_system_admin:
        return
    object_type = approval.target_type
    object_id = str(approval.target_id)

    allowed = await permissions.check(
        user_subject=f"user:{decider_open_id}",
        relation="can_admin",
        object_type=object_type,
        object_id=object_id,
    )
    if not allowed:
        if audit is not None:
            await audit.write(
                event_type="access_denied",
                actor_user_id=decider_user_id,
                details={
                    "action": "approve_approval",
                    "approval_id": str(approval.id),
                    "target": f"{object_type}:{object_id}",
                    "reason": "openfga can_admin false",
                },
                **(ctx_kwargs(ctx)),
            )
        raise ApprovalDecisionError(403, "no admin permission on approval target")


async def grant_for_approval(
    db: AsyncSession,
    permissions: PermissionsService,
    approval: ApprovalRequest,
) -> dict[str, Any]:
    """approve 通过后写 grant tuple(v4 model:subject 用飞书 open_id)。"""
    applicant = await db.get(User, approval.applicant_user_id)
    if applicant is None or not applicant.feishu_open_id:
        raise ApprovalDecisionError(400, "applicant user has no feishu_open_id")
    applicant_open_id = applicant.feishu_open_id
    target_id = str(approval.target_id)

    if approval.action == "download":
        if approval.target_type not in ("asset", "project"):
            raise ApprovalDecisionError(
                400, f"download action 不支持 target_type={approval.target_type}"
            )
        if approval.duration_seconds is None:
            raise ApprovalDecisionError(400, "download 必须有 duration_seconds")
        await permissions.grant_explicit_download(
            user_open_id=applicant_open_id,
            object_type=approval.target_type,  # type: ignore[arg-type]
            object_id=target_id,
            duration_seconds=approval.duration_seconds,
        )
        return {
            "user": f"user:{applicant_open_id}",
            "relation": "explicit_downloader",
            "object": f"{approval.target_type}:{target_id}",
            "duration_seconds": approval.duration_seconds,
        }

    # action == 'access' → sensitive_folder 邀请;v4 model 需 level(默认 viewer)
    await permissions.invite_to_sensitive_folder(
        sensitive_folder_id=target_id,
        subject=f"user:{applicant_open_id}",
        level="viewer",
        duration_seconds=approval.duration_seconds,
    )
    permanent = approval.duration_seconds is None
    return {
        "user": f"user:{applicant_open_id}",
        "relation": ("invited_viewer" if permanent else "explicit_invited_viewer"),
        "object": f"sensitive_folder:{target_id}",
        "duration_seconds": approval.duration_seconds,
    }


async def decide(
    *,
    db: AsyncSession,
    approval_id: uuid.UUID,
    decider_user_id: uuid.UUID,
    decider_open_id: str,
    decision: Literal["approve", "reject"],
    decision_note: str | None,
    permissions: PermissionsService,
    audit: AuditService,
    ctx: DecisionContext | None = None,
    is_system_admin: bool = False,
) -> ApprovalRequest:
    approval = await fetch_pending(db, approval_id)
    await enforce_admin_for_target(
        permissions, decider_user_id, decider_open_id, approval,
        audit=audit, ctx=ctx, is_system_admin=is_system_admin,
    )

    granted_ref: dict[str, Any] = {}
    if decision == "approve":
        granted_ref = await grant_for_approval(db, permissions, approval)
        approval.status = "approved"
    else:
        approval.status = "rejected"

    approval.approver_user_id = decider_user_id
    approval.decided_at = datetime.now(timezone.utc)
    approval.decision_note = decision_note
    if granted_ref:
        # merge,不要覆盖 — a2 notify_pending 把 message_ids 存在 _notify key,
        # IM 卡片 update 链路要复用,直接覆盖会丢
        merged = dict(approval.granted_tuple_ref or {})
        merged.update(granted_ref)
        approval.granted_tuple_ref = merged
    await db.commit()
    await db.refresh(approval)

    await audit.write(
        event_type="approval_state_changed",
        actor_user_id=decider_user_id,
        target_asset_id=approval.target_id if approval.target_type == "asset" else None,
        details={
            "approval_id": str(approval.id),
            "new_status": approval.status,
            "granted_tuple": granted_ref if granted_ref else None,
            "decision_note": decision_note,
            "applicant_user_id": str(approval.applicant_user_id),
        },
        **(ctx_kwargs(ctx)),
    )
    log.info("approval %s %s by=%s grant=%s",
             approval.id, approval.status, decider_user_id, granted_ref)
    return approval


def ctx_kwargs(ctx: DecisionContext | None) -> dict[str, str | None]:
    if ctx is None:
        return {"request_ip": None, "user_agent": None}
    return {"request_ip": ctx.request_ip, "user_agent": ctx.user_agent}
