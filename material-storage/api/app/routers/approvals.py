"""approvals router — 申请下载/访问 + admin 批准/拒绝。

endpoints:
  POST  /api/v1/approvals                    — 提交申请(任意认证用户)
  GET   /api/v1/approvals                    — 列表(self / admin)
  GET   /api/v1/approvals/{id}               — 单条详情
  POST  /api/v1/approvals/{id}/approve       — admin 批准 → 写 OpenFGA grant
  POST  /api/v1/approvals/{id}/reject        — admin 拒绝

iter7 接入:
- 创建后 BackgroundTask 推 IM 卡片给 target admin(approvals_notify.notify_pending)
- 决策后 BackgroundTask 推结果卡给申请者(approvals_notify.notify_decided)
- card.action.trigger 'approval_decision' 回调亦走 approval_service.decide
  (services/feishu_card_handlers.handle_approval_decision)

admin 判定:依赖 OpenFGA can_admin 关系(approval_service.enforce_admin_for_target):
  target_type=asset            → can_delete on asset
  target_type=sensitive_folder → can_admin on sensitive_folder
  target_type=project          → can_admin on project
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.tables import ApprovalRequest
from app.deps import (
    get_audit,
    CurrentUser,
    get_current_user,
    get_feishu_client,
    get_is_system_admin,
    get_permissions,
    get_request_context,
)
from app.models import ApprovalCreateIn, ApprovalDecisionIn, ApprovalOut
from app.services.approval_service import (
    ApprovalDecisionError,
    DecisionContext,
    decide,
)
from app.services.approvals_notify import (
    run_notify_decided_bg,
    run_notify_pending_bg,
)
from app.services.audit import AuditService
from app.services.feishu_client import FeishuClient
from app.services.permissions import PermissionsService
from app.settings import get_settings

log = logging.getLogger(__name__)
router = APIRouter()


@router.post("", response_model=ApprovalOut, status_code=201)
async def create_approval(
    payload: ApprovalCreateIn,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    audit: AuditService = Depends(get_audit),
    permissions: PermissionsService = Depends(get_permissions),
    feishu: FeishuClient = Depends(get_feishu_client),
    user: CurrentUser = Depends(get_current_user),
    ctx: dict = Depends(get_request_context),
) -> ApprovalOut:
    user_id, user_open_id = user.id, user.open_id
    if payload.action == "access" and payload.target_type != "sensitive_folder":
        raise HTTPException(400, "action=access 仅适用于 target_type=sensitive_folder")
    if payload.action == "download" and payload.duration_seconds is None:
        raise HTTPException(400, "action=download 必须指定 duration_seconds")

    approval = ApprovalRequest(
        id=uuid.uuid4(),
        applicant_user_id=user_id,
        target_type=payload.target_type,
        target_id=payload.target_id,
        action=payload.action,
        duration_seconds=payload.duration_seconds,
        reason=payload.reason,
        status="pending",
    )
    db.add(approval)
    await db.commit()
    await db.refresh(approval)

    await audit.write(
        event_type="approval_submitted",
        actor_user_id=user_id,
        target_asset_id=payload.target_id if payload.target_type == "asset" else None,
        details={
            "approval_id": str(approval.id),
            "target_type": payload.target_type,
            "target_id": str(payload.target_id),
            "action": payload.action,
            "duration_seconds": payload.duration_seconds,
            "reason": payload.reason[:200],
        },
        **ctx,
    )
    log.info("approval submitted id=%s applicant=%s target=%s:%s",
             approval.id, user_id, payload.target_type, payload.target_id)

    # iter7:推 IM 卡片给 target admin(BackgroundTask,失败不影响主流程)
    background.add_task(
        run_notify_pending_bg,
        approval_id=approval.id,
        feishu=feishu,
        permissions=permissions,
        settings=get_settings(),
    )
    return ApprovalOut.model_validate(approval)


@router.get("", response_model=list[ApprovalOut])
async def list_approvals(
    status_filter: str | None = Query(None, alias="status",
                                       pattern=r"^(pending|approved|rejected|revoked|expired)$"),
    scope: str = Query("self", pattern=r"^(self|all)$"),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
    limit: int = 50,
    offset: int = 0,
) -> list[ApprovalOut]:
    user_id, user_open_id = user.id, user.open_id
    stmt = select(ApprovalRequest)
    if scope == "self":
        stmt = stmt.where(ApprovalRequest.applicant_user_id == user_id)
    if status_filter:
        stmt = stmt.where(ApprovalRequest.status == status_filter)
    stmt = stmt.order_by(ApprovalRequest.created_at.desc()).limit(limit).offset(offset)
    res = await db.execute(stmt)
    return [ApprovalOut.model_validate(r) for r in res.scalars().all()]


@router.get("/{approval_id}", response_model=ApprovalOut)
async def get_approval(
    approval_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> ApprovalOut:
    user_id, user_open_id = user.id, user.open_id
    approval = await db.get(ApprovalRequest, approval_id)
    if not approval:
        raise HTTPException(404, "approval not found")
    if approval.applicant_user_id != user_id and approval.approver_user_id != user_id:
        # admin 走 list scope=all;详情仅申请人 / 决策人
        raise HTTPException(403, "not your approval")
    return ApprovalOut.model_validate(approval)


@router.post("/{approval_id}/approve", response_model=ApprovalOut)
async def approve(
    approval_id: uuid.UUID,
    payload: ApprovalDecisionIn,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    permissions: PermissionsService = Depends(get_permissions),
    audit: AuditService = Depends(get_audit),
    feishu: FeishuClient = Depends(get_feishu_client),
    user: CurrentUser = Depends(get_current_user),
    is_system_admin: bool = Depends(get_is_system_admin),
    ctx: dict = Depends(get_request_context),
) -> ApprovalOut:
    user_id, user_open_id = user.id, user.open_id
    try:
        approval = await decide(
            db=db,
            approval_id=approval_id,
            decider_user_id=user_id,
            decider_open_id=user_open_id,
            decision="approve",
            decision_note=payload.decision_note,
            permissions=permissions,
            audit=audit,
            ctx=DecisionContext(**ctx),
            is_system_admin=is_system_admin,
        )
    except ApprovalDecisionError as e:
        raise HTTPException(e.status_code, e.message) from e

    background.add_task(
        run_notify_decided_bg,
        approval_id=approval.id,
        feishu=feishu,
        settings=get_settings(),
    )
    return ApprovalOut.model_validate(approval)


@router.post("/{approval_id}/reject", response_model=ApprovalOut)
async def reject(
    approval_id: uuid.UUID,
    payload: ApprovalDecisionIn,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    permissions: PermissionsService = Depends(get_permissions),
    audit: AuditService = Depends(get_audit),
    feishu: FeishuClient = Depends(get_feishu_client),
    user: CurrentUser = Depends(get_current_user),
    is_system_admin: bool = Depends(get_is_system_admin),
    ctx: dict = Depends(get_request_context),
) -> ApprovalOut:
    user_id, user_open_id = user.id, user.open_id
    try:
        approval = await decide(
            db=db,
            approval_id=approval_id,
            decider_user_id=user_id,
            decider_open_id=user_open_id,
            decision="reject",
            decision_note=payload.decision_note,
            permissions=permissions,
            audit=audit,
            ctx=DecisionContext(**ctx),
            is_system_admin=is_system_admin,
        )
    except ApprovalDecisionError as e:
        raise HTTPException(e.status_code, e.message) from e

    background.add_task(
        run_notify_decided_bg,
        approval_id=approval.id,
        feishu=feishu,
        settings=get_settings(),
    )
    return ApprovalOut.model_validate(approval)
