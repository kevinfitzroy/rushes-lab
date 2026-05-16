"""projects router — CRUD + OpenFGA enforce + audit 落库(iter4)。

行为:
  POST /projects        — 创建项目(无 enforce;假设是 admin 操作,iter5 SSO 后加 admin check)
                          + bootstrap_project(OpenFGA tuple)+ audit
  GET  /projects        — 返回 user 可见的项目:
                          OpenFGA list_objects(user, can_view, project)
                          UNION project.visibility = 'public'
  GET  /projects/{id}   — check can_view + audit
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.tables import Project
from app.deps import (
    get_audit,
    get_current_user_id,
    get_permissions,
    get_request_context,
)
from app.models import ProjectCreateIn, ProjectOut
from app.services.audit import AuditService
from app.services.permissions import PermissionsService

router = APIRouter()


@router.post("", response_model=ProjectOut, status_code=201)
async def create_project(
    payload: ProjectCreateIn,
    db: AsyncSession = Depends(get_db),
    permissions: PermissionsService = Depends(get_permissions),
    audit: AuditService = Depends(get_audit),
    user_id: uuid.UUID = Depends(get_current_user_id),
    ctx: dict = Depends(get_request_context),
) -> ProjectOut:
    """创建 project + bootstrap OpenFGA tuple + audit。

    Phase B-2 iter4:不 enforce 创建权限(iter5 SSO 加 org admin check);
    任何已认证 user 可建项目。

    organization_id 解析顺序:payload > user.organization_id > settings.default_organization_id。
    创建者自动作为 project admin → OpenFGA tuple,确保 list/get 可见。
    """
    # 解析 org_id
    org_id = payload.organization_id
    if org_id is None:
        from app.db.tables import User
        user = await db.get(User, user_id)
        if user and user.organization_id:
            org_id = user.organization_id
        else:
            from app.settings import get_settings
            default = get_settings().default_organization_id
            if default:
                import uuid as _uuid
                org_id = _uuid.UUID(default)
    if org_id is None:
        raise HTTPException(400, "organization_id missing(no payload, no user org, no default)")

    project = Project(
        id=uuid.uuid4(),
        organization_id=org_id,
        code=payload.code,
        name=payload.name,
        description=payload.description,
        minio_bucket=payload.minio_bucket,
    )
    db.add(project)
    try:
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        raise HTTPException(400, detail=f"project code conflict or invalid org: {e.orig}") from e

    await permissions.bootstrap_project(
        project_id=str(project.id), organization_id=str(project.organization_id)
    )

    # 创建者立即获 project admin tuple(否则后续 list/get 看不到自己刚建的项目)
    try:
        from openfga_sdk.client.models import ClientTuple, ClientWriteRequest
        await permissions._client.write(  # type: ignore[attr-defined]
            ClientWriteRequest(writes=[
                ClientTuple(
                    user=f"user:{user_id}", relation="admin",
                    object=f"project:{project.id}",
                ),
            ])
        )
    except Exception as e:
        # tuple 重复 / 其他错误不阻塞;但 log
        import logging
        logging.getLogger(__name__).warning("creator admin tuple write tolerated: %s", e)

    await audit.write(
        event_type="project_created",
        actor_user_id=user_id,
        target_project_id=project.id,
        details={"code": project.code, "name": project.name, "visibility": project.visibility},
        **ctx,
    )

    await db.refresh(project)
    return ProjectOut.model_validate(project)


@router.get("", response_model=list[ProjectOut])
async def list_projects(
    db: AsyncSession = Depends(get_db),
    permissions: PermissionsService = Depends(get_permissions),
    user_id: uuid.UUID = Depends(get_current_user_id),
    limit: int = 50,
    offset: int = 0,
) -> list[ProjectOut]:
    """返回 user 可见的项目:OpenFGA list_objects UNION visibility=public。"""
    # OpenFGA:user 是 member / editor / admin 的项目(can_view 关系)
    member_ids = await permissions.list_objects(
        user_id=str(user_id), relation="can_view", object_type="project"
    )
    member_uuids = [uuid.UUID(s) for s in member_ids]

    # SQL:UNION public projects;过滤已 archived
    stmt = (
        select(Project)
        .where(
            or_(
                Project.id.in_(member_uuids) if member_uuids else False,
                Project.visibility == "public",
            ),
            Project.is_archived.is_(False),
        )
        .order_by(Project.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    res = await db.execute(stmt)
    rows = res.scalars().all()
    return [ProjectOut.model_validate(r) for r in rows]


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    permissions: PermissionsService = Depends(get_permissions),
    audit: AuditService = Depends(get_audit),
    user_id: uuid.UUID = Depends(get_current_user_id),
    ctx: dict = Depends(get_request_context),
) -> ProjectOut:
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "project not found")

    # public visibility 直接通过;否则 OpenFGA check can_view
    if project.visibility != "public":
        allowed = await permissions.check(
            user_id=str(user_id),
            relation="can_view",
            object_type="project",
            object_id=str(project_id),
        )
        if not allowed:
            await audit.write(
                event_type="access_denied",
                actor_user_id=user_id,
                target_project_id=project_id,
                details={"action": "get_project", "reason": "openfga can_view false"},
                **ctx,
            )
            raise HTTPException(403, "no permission to view project")

    return ProjectOut.model_validate(project)
