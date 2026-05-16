"""approvals router — 申请下载/访问 + admin 批准/拒绝(Phase B-2 iter6)。

endpoints:
  POST  /api/v1/approvals                    — 提交申请(任意认证用户)
  GET   /api/v1/approvals                    — 列表(self / admin)
  GET   /api/v1/approvals/{id}               — 单条详情
  POST  /api/v1/approvals/{id}/approve       — admin 批准 → 写 OpenFGA grant
  POST  /api/v1/approvals/{id}/reject        — admin 拒绝

admin 判定:依赖 OpenFGA can_admin 关系:
  target_type=asset           → check user can_admin on asset's parent folder/project
  target_type=sensitive_folder → check user can_admin on sensitive_folder
  target_type=project         → check user can_admin on project

iter7 接飞书 OpenAPI 时:POST /approvals 同时调
lark-oapi 创建审批 instance,把 instance_code 存 approvals.feishu_instance_code;
webhook 收到 approval_instance.event → 调内部 /approve 或 /reject。
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.tables import ApprovalRequest, Asset, Folder
from app.deps import (
    get_audit,
    get_current_user_id,
    get_permissions,
    get_request_context,
)
from app.models import ApprovalCreateIn, ApprovalDecisionIn, ApprovalOut
from app.services.audit import AuditService
from app.services.permissions import PermissionsService

log = logging.getLogger(__name__)
router = APIRouter()


@router.post("", response_model=ApprovalOut, status_code=201)
async def create_approval(
    payload: ApprovalCreateIn,
    db: AsyncSession = Depends(get_db),
    audit: AuditService = Depends(get_audit),
    user_id: uuid.UUID = Depends(get_current_user_id),
    ctx: dict = Depends(get_request_context),
) -> ApprovalOut:
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

    # iter7:这里调 lark-oapi 创建飞书审批 instance,存 feishu_instance_code
    return ApprovalOut.model_validate(approval)


@router.get("", response_model=list[ApprovalOut])
async def list_approvals(
    status_filter: str | None = Query(None, alias="status",
                                       pattern=r"^(pending|approved|rejected|revoked|expired)$"),
    scope: str = Query("self", pattern=r"^(self|all)$",
                       description="self=只看自己;all=admin 看全部(iter6 简化:不 enforce admin)"),
    db: AsyncSession = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
    limit: int = 50,
    offset: int = 0,
) -> list[ApprovalOut]:
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
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> ApprovalOut:
    approval = await db.get(ApprovalRequest, approval_id)
    if not approval:
        raise HTTPException(404, "approval not found")
    # 申请人 / 决策人 / admin 可看(简化:申请人 + 决策人;admin 在 list scope=all)
    if approval.applicant_user_id != user_id and approval.approver_user_id != user_id:
        # iter7 加 admin check
        raise HTTPException(403, "not your approval")
    return ApprovalOut.model_validate(approval)


@router.post("/{approval_id}/approve", response_model=ApprovalOut)
async def approve(
    approval_id: uuid.UUID,
    payload: ApprovalDecisionIn,
    db: AsyncSession = Depends(get_db),
    permissions: PermissionsService = Depends(get_permissions),
    audit: AuditService = Depends(get_audit),
    user_id: uuid.UUID = Depends(get_current_user_id),
    ctx: dict = Depends(get_request_context),
) -> ApprovalOut:
    approval = await _get_pending_or_404(db, approval_id)

    # admin 校验:user 必须对申请目标 can_admin
    await _enforce_admin_for_target(permissions, user_id, approval, audit, ctx)

    # 写 OpenFGA grant
    granted_ref = await _grant_for_approval(permissions, approval)

    # 落库
    approval.status = "approved"
    approval.approver_user_id = user_id
    approval.decided_at = datetime.now(timezone.utc)
    approval.decision_note = payload.decision_note
    approval.granted_tuple_ref = granted_ref
    await db.commit()
    await db.refresh(approval)

    await audit.write(
        event_type="approval_state_changed",
        actor_user_id=user_id,
        target_asset_id=approval.target_id if approval.target_type == "asset" else None,
        details={
            "approval_id": str(approval.id),
            "new_status": "approved",
            "granted_tuple": granted_ref,
            "applicant_user_id": str(approval.applicant_user_id),
        },
        **ctx,
    )
    log.info("approval %s approved by=%s grant=%s", approval.id, user_id, granted_ref)
    return ApprovalOut.model_validate(approval)


@router.post("/{approval_id}/reject", response_model=ApprovalOut)
async def reject(
    approval_id: uuid.UUID,
    payload: ApprovalDecisionIn,
    db: AsyncSession = Depends(get_db),
    permissions: PermissionsService = Depends(get_permissions),
    audit: AuditService = Depends(get_audit),
    user_id: uuid.UUID = Depends(get_current_user_id),
    ctx: dict = Depends(get_request_context),
) -> ApprovalOut:
    approval = await _get_pending_or_404(db, approval_id)
    await _enforce_admin_for_target(permissions, user_id, approval, audit, ctx)

    approval.status = "rejected"
    approval.approver_user_id = user_id
    approval.decided_at = datetime.now(timezone.utc)
    approval.decision_note = payload.decision_note
    await db.commit()
    await db.refresh(approval)

    await audit.write(
        event_type="approval_state_changed",
        actor_user_id=user_id,
        target_asset_id=approval.target_id if approval.target_type == "asset" else None,
        details={"approval_id": str(approval.id), "new_status": "rejected",
                 "decision_note": payload.decision_note},
        **ctx,
    )
    return ApprovalOut.model_validate(approval)


# ─── internals ────────────────────────────────────────────────────────────────
async def _get_pending_or_404(db: AsyncSession, approval_id: uuid.UUID) -> ApprovalRequest:
    approval = await db.get(ApprovalRequest, approval_id)
    if not approval:
        raise HTTPException(404, "approval not found")
    if approval.status != "pending":
        raise HTTPException(409, f"approval already {approval.status}")
    return approval


async def _enforce_admin_for_target(
    permissions: PermissionsService,
    user_id: uuid.UUID,
    approval: ApprovalRequest,
    audit: AuditService,
    ctx: dict,
) -> None:
    """admin check:user 对申请目标必须有 admin 权限。

    model v3:
      project / sensitive_folder → can_admin relation
      asset → can_delete(= can_admin from parent;model 没 asset.can_admin)
    """
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
        await audit.write(
            event_type="access_denied",
            actor_user_id=user_id,
            details={"action": "approve_approval", "approval_id": str(approval.id),
                     "target": f"{object_type}:{object_id}",
                     "reason": "openfga can_admin false"},
            **ctx,
        )
        raise HTTPException(403, "no admin permission on approval target")


async def _grant_for_approval(
    permissions: PermissionsService, approval: ApprovalRequest
) -> dict[str, Any]:
    """根据 approval 类型写对应 OpenFGA tuple,返 tuple 引用(撤销用)。"""
    applicant = str(approval.applicant_user_id)
    target_id = str(approval.target_id)

    if approval.action == "download":
        # 临时下载 grant — 只 asset / project 支持
        if approval.target_type not in ("asset", "project"):
            raise HTTPException(400, f"download action 不支持 target_type={approval.target_type}")
        if approval.duration_seconds is None:
            raise HTTPException(400, "download 必须有 duration_seconds")
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

    # action == "access" → 邀请进 sensitive_folder
    await permissions.invite_to_sensitive_folder(
        sensitive_folder_id=target_id,
        user_id=applicant,
        duration_seconds=approval.duration_seconds,  # None = 永久
    )
    return {
        "user": f"user:{applicant}",
        "relation": "invited" if approval.duration_seconds is None else "explicit_invited",
        "object": f"sensitive_folder:{target_id}",
        "duration_seconds": approval.duration_seconds,
    }
