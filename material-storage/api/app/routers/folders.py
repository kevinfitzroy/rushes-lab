"""folders router — Phase B-2 iter7。

endpoints:
  POST   /api/v1/folders                          — 创建 folder(+bootstrap_folder OpenFGA)
                                                    需 can_edit project
  GET    /api/v1/folders?project_id=...           — 列表 user 可见的 folder
                                                    (普通 folder by project member +
                                                     sensitive_folder by list_objects can_view)
  GET    /api/v1/folders/{id}                     — 单条(can_view)
  POST   /api/v1/folders/{id}/invite              — sensitive_folder 邀请(can_admin only)
  DELETE /api/v1/folders/{id}/invite/user/{uid}   — 撤销(can_admin only)
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.tables import Folder, Project
from app.deps import (
    get_audit,
    get_current_user_id,
    get_feishu_client,
    get_permissions,
    get_request_context,
)
from app.models import FolderCreateIn, FolderInviteIn, FolderOut
from app.services.audit import AuditService
from app.services.feishu_client import FeishuClient
from app.services.invite_notify import run_notify_folder_invite_bg
from app.services.permissions import PermissionsService
from app.settings import get_settings

log = logging.getLogger(__name__)
router = APIRouter()


@router.post("", response_model=FolderOut, status_code=201)
async def create_folder(
    payload: FolderCreateIn,
    db: AsyncSession = Depends(get_db),
    permissions: PermissionsService = Depends(get_permissions),
    audit: AuditService = Depends(get_audit),
    user_id: uuid.UUID = Depends(get_current_user_id),
    ctx: dict = Depends(get_request_context),
) -> FolderOut:
    # 1) 权限:user 须 can_edit project
    allowed = await permissions.check(
        user_id=str(user_id),
        relation="can_edit",
        object_type="project",
        object_id=str(payload.project_id),
    )
    if not allowed:
        await audit.write(
            event_type="access_denied",
            actor_user_id=user_id,
            target_project_id=payload.project_id,
            details={"action": "create_folder", "reason": "openfga can_edit false"},
            **ctx,
        )
        raise HTTPException(403, "no permission to create folder in this project")

    # 2) 计算 minio_prefix
    minio_prefix = payload.minio_prefix
    if not minio_prefix:
        if payload.parent_folder_id:
            parent = await db.get(Folder, payload.parent_folder_id)
            if not parent or parent.project_id != payload.project_id:
                raise HTTPException(400, "parent_folder invalid for this project")
            minio_prefix = f"{parent.minio_prefix.rstrip('/')}/{payload.name}/"
        else:
            minio_prefix = f"{payload.name}/"

    folder = Folder(
        id=uuid.uuid4(),
        project_id=payload.project_id,
        parent_folder_id=payload.parent_folder_id,
        name=payload.name,
        minio_prefix=minio_prefix,
        is_sensitive=payload.is_sensitive,
    )
    db.add(folder)
    try:
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        raise HTTPException(400, f"folder prefix conflict: {e.orig}") from e

    # 3) bootstrap OpenFGA parent tuple
    if payload.parent_folder_id:
        # parent type = folder / sensitive_folder by parent.is_sensitive
        parent = await db.get(Folder, payload.parent_folder_id)
        assert parent is not None
        parent_type = "sensitive_folder" if parent.is_sensitive else "folder"
        parent_id = str(parent.id)
    else:
        parent_type = "project"
        parent_id = str(payload.project_id)

    await permissions.bootstrap_folder(
        folder_id=str(folder.id),
        parent_type=parent_type,  # type: ignore[arg-type]
        parent_id=parent_id,
        is_sensitive=payload.is_sensitive,
    )

    await audit.write(
        event_type="folder_created",
        actor_user_id=user_id,
        target_project_id=payload.project_id,
        details={
            "folder_id": str(folder.id),
            "name": folder.name,
            "minio_prefix": folder.minio_prefix,
            "is_sensitive": folder.is_sensitive,
            "parent_folder_id": str(payload.parent_folder_id) if payload.parent_folder_id else None,
        },
        **ctx,
    )
    log.info("folder created id=%s name=%s sensitive=%s",
             folder.id, folder.name, folder.is_sensitive)

    await db.refresh(folder)
    return FolderOut.model_validate(folder)


@router.get("", response_model=list[FolderOut])
async def list_folders(
    project_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    permissions: PermissionsService = Depends(get_permissions),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> list[FolderOut]:
    # project 可见 check(public 直通,否则 can_view)
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "project not found")
    if project.visibility != "public":
        allowed = await permissions.check(
            user_id=str(user_id), relation="can_view",
            object_type="project", object_id=str(project_id),
        )
        if not allowed:
            raise HTTPException(403, "no permission")

    # 普通 folder:project member 都可见(用 SQL 拿全部)
    # sensitive folder:OpenFGA list_objects(user, can_view, sensitive_folder) intersect this project
    sensitive_ids_str = await permissions.list_objects(
        user_id=str(user_id), relation="can_view", object_type="sensitive_folder"
    )
    sensitive_uuids = [uuid.UUID(s) for s in sensitive_ids_str]

    stmt = select(Folder).where(
        Folder.project_id == project_id,
        or_(
            Folder.is_sensitive.is_(False),                       # 普通 folder 全见
            Folder.id.in_(sensitive_uuids) if sensitive_uuids else False,  # sensitive 须 invited
        ),
    ).order_by(Folder.minio_prefix)
    res = await db.execute(stmt)
    return [FolderOut.model_validate(r) for r in res.scalars().all()]


@router.get("/{folder_id}", response_model=FolderOut)
async def get_folder(
    folder_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    permissions: PermissionsService = Depends(get_permissions),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> FolderOut:
    folder = await db.get(Folder, folder_id)
    if not folder:
        raise HTTPException(404, "folder not found")
    allowed = await permissions.check(
        user_id=str(user_id), relation="can_view",
        object_type="sensitive_folder" if folder.is_sensitive else "folder",
        object_id=str(folder.id),
    )
    if not allowed:
        raise HTTPException(403, "no permission")
    return FolderOut.model_validate(folder)


@router.post("/{folder_id}/invite", status_code=204)
async def invite(
    folder_id: uuid.UUID,
    payload: FolderInviteIn,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    permissions: PermissionsService = Depends(get_permissions),
    audit: AuditService = Depends(get_audit),
    feishu: FeishuClient = Depends(get_feishu_client),
    user_id: uuid.UUID = Depends(get_current_user_id),
    ctx: dict = Depends(get_request_context),
) -> None:
    """直接邀请 user / group 进入 sensitive_folder(绕过审批,admin 操作)。

    审批驱动的邀请走 /api/v1/approvals。"""
    folder = await db.get(Folder, folder_id)
    if not folder:
        raise HTTPException(404, "folder not found")
    if not folder.is_sensitive:
        raise HTTPException(400, "only sensitive_folder needs invite")

    if (payload.user_id is None) == (payload.group_id is None):
        raise HTTPException(400, "must specify exactly one of user_id / group_id")

    # admin check
    allowed = await permissions.check(
        user_id=str(user_id), relation="can_admin",
        object_type="sensitive_folder", object_id=str(folder_id),
    )
    if not allowed:
        await audit.write(
            event_type="access_denied",
            actor_user_id=user_id,
            target_project_id=folder.project_id,
            details={"action": "invite_sensitive_folder", "folder_id": str(folder_id),
                     "reason": "openfga can_admin false"},
            **ctx,
        )
        raise HTTPException(403, "no admin permission on this folder")

    await permissions.invite_to_sensitive_folder(
        sensitive_folder_id=str(folder_id),
        user_id=str(payload.user_id) if payload.user_id else None,
        group_id=str(payload.group_id) if payload.group_id else None,
        duration_seconds=payload.duration_seconds,
    )

    await audit.write(
        event_type="sensitive_folder_invited",
        actor_user_id=user_id,
        target_project_id=folder.project_id,
        details={
            "folder_id": str(folder_id),
            "invitee_user_id": str(payload.user_id) if payload.user_id else None,
            "invitee_group_id": str(payload.group_id) if payload.group_id else None,
            "permanent": payload.duration_seconds is None,
            "duration_seconds": payload.duration_seconds,
        },
        **ctx,
    )

    # iter4:user 邀请推 IM 卡(group 邀请没 feishu_open_id,跳过)
    if payload.user_id is not None:
        background.add_task(
            run_notify_folder_invite_bg,
            folder_id=folder_id,
            invitee_user_id=payload.user_id,
            inviter_user_id=user_id,
            duration_seconds=payload.duration_seconds,
            feishu=feishu,
            settings=get_settings(),
        )


@router.delete("/{folder_id}/invite/user/{invitee_id}", status_code=204)
async def revoke_user_invite(
    folder_id: uuid.UUID,
    invitee_id: uuid.UUID,
    permanent: bool = Query(True, description="True=删 invited(永久);False=删 explicit_invited(临时)"),
    db: AsyncSession = Depends(get_db),
    permissions: PermissionsService = Depends(get_permissions),
    audit: AuditService = Depends(get_audit),
    user_id: uuid.UUID = Depends(get_current_user_id),
    ctx: dict = Depends(get_request_context),
) -> None:
    folder = await db.get(Folder, folder_id)
    if not folder:
        raise HTTPException(404, "folder not found")
    if not folder.is_sensitive:
        raise HTTPException(400, "not a sensitive_folder")

    allowed = await permissions.check(
        user_id=str(user_id), relation="can_admin",
        object_type="sensitive_folder", object_id=str(folder_id),
    )
    if not allowed:
        raise HTTPException(403, "no admin permission")

    await permissions.revoke_from_sensitive_folder(
        sensitive_folder_id=str(folder_id),
        user_id=str(invitee_id),
        permanent=permanent,
    )

    await audit.write(
        event_type="sensitive_folder_revoked",
        actor_user_id=user_id,
        target_project_id=folder.project_id,
        details={
            "folder_id": str(folder_id),
            "invitee_user_id": str(invitee_id),
            "permanent": permanent,
        },
        **ctx,
    )
