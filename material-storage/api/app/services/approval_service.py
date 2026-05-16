"""审批决策核心服务 — 抽自 routers/approvals.py。

iter7 飞书 IM 卡片接入后,decision 入口有两个:
  1. HTTP:POST /api/v1/approvals/{id}/approve|reject — router endpoint
  2. 飞书卡片回调:card.action.trigger value.intent='approval_decision' — feishu_card_handlers

两个入口必须走同一段权限校验 + grant 写入 + 落库 + audit 逻辑,所以抽到这里。
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.tables import ApprovalRequest
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
    """请求级 context — 写 audit 用(IP / User-Agent)。card handler 路径多数为空。"""

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
    user_id: uuid.UUID,
    approval: ApprovalRequest,
    *,
    audit: AuditService | None = None,
    ctx: DecisionContext | None = None,
) -> None:
    """user 必须对申请目标 can_admin(asset 走 can_delete,project/sensitive_folder 走 can_admin)。"""
    object_type = approval.target_type
    object_id = str(approval.target_id)
    admin_relation = "can_delete" if object_type == "asset" else "can_admin"

    allowed = await permissions.check(
        user_id=str(user_id),
        relation=admin_relation,
        object_type=object_type,
        object_id=object_id,
    )
    if not allowed:
        if audit is not None:
            await audit.write(
                event_type="access_denied",
                actor_user_id=user_id,
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
    permissions: PermissionsService, approval: ApprovalRequest
) -> dict[str, Any]:
    """写 grant tuple,返 tuple ref(撤销/审计用)。"""
    applicant = str(approval.applicant_user_id)
    target_id = str(approval.target_id)

    if approval.action == "download":
        if approval.target_type not in ("asset", "project"):
            raise ApprovalDecisionError(
                400, f"download action 不支持 target_type={approval.target_type}"
            )
        if approval.duration_seconds is None:
            raise ApprovalDecisionError(400, "download 必须有 duration_seconds")
        await permissions.grant_explicit_download(
            user_id=applicant,
            object_type=approval.target_type,  # type: ignore[arg-type]
            object_id=target_id,
            duration_seconds=approval.duration_seconds,
        )
        return {
            "user": f"user:{applicant}",
            "relation": "explicit_downloader",
            "object": f"{approval.target_type}:{target_id}",
            "duration_seconds": approval.duration_seconds,
        }

    # action=='access' → sensitive_folder 邀请
    await permissions.invite_to_sensitive_folder(
        sensitive_folder_id=target_id,
        user_id=applicant,
        duration_seconds=approval.duration_seconds,
    )
    return {
        "user": f"user:{applicant}",
        "relation": "invited" if approval.duration_seconds is None else "explicit_invited",
        "object": f"sensitive_folder:{target_id}",
        "duration_seconds": approval.duration_seconds,
    }


async def decide(
    *,
    db: AsyncSession,
    approval_id: uuid.UUID,
    decider_user_id: uuid.UUID,
    decision: Literal["approve", "reject"],
    decision_note: str | None,
    permissions: PermissionsService,
    audit: AuditService,
    ctx: DecisionContext | None = None,
) -> ApprovalRequest:
    """approve 或 reject 一个 pending approval — router/card handler 唯一入口。

    抛 ApprovalDecisionError(status_code, msg)给调用方,无副作用回滚。
    """
    approval = await fetch_pending(db, approval_id)
    await enforce_admin_for_target(permissions, decider_user_id, approval, audit=audit, ctx=ctx)

    granted_ref: dict[str, Any] = {}
    if decision == "approve":
        granted_ref = await grant_for_approval(permissions, approval)
        approval.status = "approved"
    else:
        approval.status = "rejected"

    approval.approver_user_id = decider_user_id
    approval.decided_at = datetime.now(timezone.utc)
    approval.decision_note = decision_note
    if granted_ref:
        approval.granted_tuple_ref = granted_ref
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
