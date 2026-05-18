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

import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.tables import Project
from app.deps import (
    get_audit,
    CurrentUser,
    get_current_user,
    get_is_system_admin,
    get_permissions,
    get_request_context,
    require_system_admin,
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
    user: CurrentUser = Depends(require_system_admin),   # 仅系统 admin 可建
    ctx: dict = Depends(get_request_context),
) -> ProjectOut:
    """创建 project — **仅系统 admin 可调**;必须 payload 明确指派项目 admin
    (可以指自己,UI 默认填创建者)。

    organization_id 解析顺序:payload > user.organization_id > settings.default_organization_id。
    """
    user_id = user.id
    from app.db.tables import Organization, User

    # 校验 admin 是真 user(存在 db + 飞书 open_id)
    from sqlalchemy import select as _select
    res = await db.execute(_select(User).where(
        User.feishu_open_id == payload.admin_user_open_id,
        User.is_active.is_(True),
    ))
    admin_user = res.scalar_one_or_none()
    if admin_user is None:
        raise HTTPException(
            400, f"admin user not found:{payload.admin_user_open_id}(需先 OIDC 登录过)"
        )

    # 解析 org_id
    org_id = payload.organization_id
    if org_id is None:
        db_user = await db.get(User, user_id)
        if db_user and db_user.organization_id:
            org_id = db_user.organization_id
        else:
            from app.settings import get_settings
            default = get_settings().default_organization_id
            if default:
                org_id = uuid.UUID(default)
    if org_id is None:
        raise HTTPException(400, "organization_id missing(no payload, no user org, no default)")

    org = await db.get(Organization, org_id)
    if org is None:
        raise HTTPException(400, f"organization {org_id} not found")
    tenant_key = org.feishu_tenant_key or str(org_id)

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
        err = str(e.orig)
        if "projects_code_key" in err:
            raise HTTPException(409, "项目 code 已存在") from e
        if "organization_id" in err:
            raise HTTPException(400, "organization 不存在或无效") from e
        raise HTTPException(400, "项目创建失败,可能存在唯一性冲突") from e

    # bootstrap:org parent + 指派的项目 admin(可与创建者不同)
    await permissions.bootstrap_project(
        project_id=str(project.id),
        organization_tenant_key=tenant_key,
        creator_open_id=payload.admin_user_open_id,
    )

    await audit.write(
        event_type="project_created",
        actor_user_id=user_id,
        target_project_id=project.id,
        details={
            "code": project.code, "name": project.name,
            "visibility": project.visibility,
            "admin_user_open_id": payload.admin_user_open_id,
            "admin_name": admin_user.name,
        },
        **ctx,
    )

    await db.refresh(project)
    return ProjectOut.model_validate(project)


async def _fill_project_admins(
    db: AsyncSession,
    permissions: PermissionsService,
    projects: list,
) -> dict[uuid.UUID, list]:
    """对一批 project 批量查 OpenFGA admin 并反查 db name → {project_id: [AdminBrief]}。

    每个 project 一次 OpenFGA list_users(N 次 round-trip,PoC 量级可接受;
    后续可加缓存或一次性 batch)。
    """
    from app.db.tables import User
    from app.models import AdminBrief

    out: dict[uuid.UUID, list] = {}
    all_open_ids: set[str] = set()
    project_to_open_ids: dict[uuid.UUID, list[str]] = {}
    for p in projects:
        ids = await permissions.list_users_with_relation(
            object_type="project", object_id=str(p.id), relation="admin",
        )
        project_to_open_ids[p.id] = ids
        all_open_ids.update(ids)

    name_by_open_id: dict[str, str] = {}
    if all_open_ids:
        res = await db.execute(
            select(User.feishu_open_id, User.name).where(
                User.feishu_open_id.in_(all_open_ids)
            )
        )
        name_by_open_id = {row[0]: row[1] for row in res.all()}

    for pid, ids in project_to_open_ids.items():
        out[pid] = [
            AdminBrief(open_id=oid, name=name_by_open_id.get(oid, oid[:12] + "…"))
            for oid in ids
        ]
    return out


@router.get("", response_model=list[ProjectOut])
async def list_projects(
    db: AsyncSession = Depends(get_db),
    permissions: PermissionsService = Depends(get_permissions),
    user: CurrentUser = Depends(get_current_user),
    is_system_admin: bool = Depends(get_is_system_admin),
    limit: int = 100,
    offset: int = 0,
) -> list[ProjectOut]:
    """返回 user 可见的项目 + 各项目的 admin 列表。

    系统 admin(organization.admin)→ 见全部 active project,无 filter
    普通 user → OpenFGA list_objects(can_view, project) UNION visibility=public
    """
    user_open_id = user.open_id

    if is_system_admin:
        stmt = (
            select(Project)
            .where(Project.is_archived.is_(False))
            .order_by(Project.created_at.desc())
            .limit(limit).offset(offset)
        )
    else:
        member_ids = await permissions.list_objects(
            user_subject=f"user:{user_open_id}", relation="can_view", object_type="project",
        )
        member_uuids = [uuid.UUID(s) for s in member_ids]
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
            .limit(limit).offset(offset)
        )
    res = await db.execute(stmt)
    rows = list(res.scalars().all())

    # batch fill admins + my_roles
    admins_by_pid = await _fill_project_admins(db, permissions, rows)
    my_roles_by_pid = await _fill_my_roles(
        permissions, user_open_id, rows, is_system_admin=is_system_admin,
    )
    out: list[ProjectOut] = []
    for r in rows:
        po = ProjectOut.model_validate(r)
        po.admins = admins_by_pid.get(r.id, [])
        po.my_roles = my_roles_by_pid.get(r.id, [])
        out.append(po)
    return out


_PROJECT_ROLES: tuple[str, ...] = ("admin", "uploader", "downloader", "viewer")


async def _fill_my_roles(
    permissions: PermissionsService,
    user_open_id: str,
    projects: list,
    *,
    is_system_admin: bool,
) -> dict[uuid.UUID, list[str]]:
    """每个 project 上 user 的有效 role list。

    系统 admin → 全 admin(超级权限)
    否则:1 次 list_objects/role(4 次总),N 个 project 走集合 lookup
    — O(1) FGA calls,避免 N×4 串行回路。
    """
    out: dict[uuid.UUID, list[str]] = {}
    if is_system_admin:
        for p in projects:
            out[p.id] = ["admin"]
        return out
    if not projects:
        return out

    user_subject = f"user:{user_open_id}"
    role_lists = await asyncio.gather(*[
        permissions.list_objects(
            user_subject=user_subject, relation=role, object_type="project",
        )
        for role in _PROJECT_ROLES
    ])
    role_sets = {r: set(ids) for r, ids in zip(_PROJECT_ROLES, role_lists)}

    for p in projects:
        pid = str(p.id)
        out[p.id] = [r for r in _PROJECT_ROLES if pid in role_sets[r]]
    return out


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    permissions: PermissionsService = Depends(get_permissions),
    audit: AuditService = Depends(get_audit),
    user: CurrentUser = Depends(get_current_user),
    is_system_admin: bool = Depends(get_is_system_admin),
    ctx: dict = Depends(get_request_context),
) -> ProjectOut:
    user_id, user_open_id = user.id, user.open_id
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "project not found")

    if not is_system_admin and project.visibility != "public":
        allowed = await permissions.check(
            user_subject=f"user:{user_open_id}",
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

    po = ProjectOut.model_validate(project)
    admins_by_pid = await _fill_project_admins(db, permissions, [project])
    po.admins = admins_by_pid.get(project.id, [])
    my_roles_by_pid = await _fill_my_roles(
        permissions, user_open_id, [project], is_system_admin=is_system_admin,
    )
    po.my_roles = my_roles_by_pid.get(project.id, [])
    return po


# ─── project members CRUD (D iter4) ──────────────────────────────────────────
PROJECT_ROLES = ("admin", "uploader", "downloader", "viewer")


async def _enforce_project_admin(
    permissions: PermissionsService, audit: AuditService,
    user_id: uuid.UUID, user_open_id: str, project_id: uuid.UUID, action: str, ctx: dict,
    *, is_system_admin: bool = False,
) -> None:
    if is_system_admin:
        return  # 系统 admin 直通,所有项目都可管理
    ok = await permissions.check(
        user_subject=f"user:{user_open_id}", relation="can_admin",
        object_type="project", object_id=str(project_id),
    )
    if not ok:
        await audit.write(
            event_type="access_denied", actor_user_id=user_id,
            target_project_id=project_id,
            details={"action": action, "reason": "openfga can_admin false"},
            **ctx,
        )
        raise HTTPException(403, "no admin permission on this project")


@router.get("/{project_id}/members")
async def list_project_members(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    permissions: PermissionsService = Depends(get_permissions),
    audit: AuditService = Depends(get_audit),
    user: CurrentUser = Depends(get_current_user),
    is_system_admin: bool = Depends(get_is_system_admin),
    ctx: dict = Depends(get_request_context),
) -> list[dict]:
    """project 成员列表 — D iter4 前端 ProjectMembersDrawer 用。

    返:[{subject, kind, subject_id, name, roles: [admin|viewer|downloader|uploader, ...]}]
    同一 subject 多 role 聚合。需 can_admin project。
    """
    user_id, user_open_id = user.id, user.open_id
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "project not found")
    await _enforce_project_admin(
        permissions, audit, user_id, user_open_id, project_id, "list_members", ctx,
        is_system_admin=is_system_admin,
    )

    from openfga_sdk.models import ReadRequestTupleKey
    from app.db.tables import User as _User
    resp = await permissions._client.read(  # type: ignore[attr-defined]
        ReadRequestTupleKey(object=f"project:{project_id}")
    )

    by_subject: dict[str, dict] = {}
    user_subject_ids: list[str] = []

    for t in resp.tuples:
        rel = t.key.relation
        if rel not in PROJECT_ROLES:
            continue
        subject = t.key.user
        kind, rest = subject.split(":", 1)
        sid = rest.rsplit("#", 1)[0]
        key = subject
        if key not in by_subject:
            by_subject[key] = {
                "subject": subject, "kind": kind, "subject_id": sid,
                "name": None, "roles": [],
            }
            if kind == "user":
                user_subject_ids.append(sid)
        by_subject[key]["roles"].append(rel)

    # user batch db lookup
    if user_subject_ids:
        stmt = select(_User).where(_User.feishu_open_id.in_(user_subject_ids))
        res = await db.execute(stmt)
        name_by_open_id = {u.feishu_open_id: u.name for u in res.scalars().all()}
        for m in by_subject.values():
            if m["kind"] == "user":
                m["name"] = name_by_open_id.get(m["subject_id"], m["subject_id"][:12] + "…")
    for m in by_subject.values():
        if m["name"] is None:
            label = "用户组" if m["kind"] == "group" else "部门" if m["kind"] == "department" else m["kind"]
            m["name"] = f"{label} {m['subject_id'][:12]}…"

    members = list(by_subject.values())
    # 排序:admin 优先 → user 优先 → name
    role_rank = {"admin": 0, "uploader": 1, "downloader": 2, "viewer": 3}
    def rank(m: dict) -> tuple:
        top = min((role_rank.get(r, 9) for r in m["roles"]), default=9)
        kind_rank = 0 if m["kind"] == "user" else 1
        return (top, kind_rank, m["name"] or "")
    members.sort(key=rank)
    return members


@router.post("/{project_id}/members", status_code=204)
async def add_project_member(
    project_id: uuid.UUID,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    permissions: PermissionsService = Depends(get_permissions),
    audit: AuditService = Depends(get_audit),
    user: CurrentUser = Depends(get_current_user),
    is_system_admin: bool = Depends(get_is_system_admin),
    ctx: dict = Depends(get_request_context),
) -> None:
    """加 project 成员。

    body: {
      user_open_id?: str | group_id?: str | department_id?: str,  # 三选一
      role: 'admin'|'viewer'|'downloader'|'uploader'
    }
    需 can_admin project。
    """
    user_id, user_open_id = user.id, user.open_id
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "project not found")
    await _enforce_project_admin(
        permissions, audit, user_id, user_open_id, project_id, "add_member", ctx,
        is_system_admin=is_system_admin,
    )

    role = payload.get("role")
    if role not in PROJECT_ROLES:
        raise HTTPException(400, f"role must be one of {PROJECT_ROLES}")

    provided = [
        ("user", payload.get("user_open_id")),
        ("group", payload.get("group_id")),
        ("department", payload.get("department_id")),
    ]
    chosen = [(k, v) for k, v in provided if v]
    if len(chosen) != 1:
        raise HTTPException(400, "must specify exactly one of user_open_id / group_id / department_id")
    if role == "admin" and chosen[0][0] != "user":
        # model v4 限 admin: [user, group#member] — 不允许 department#member
        if chosen[0][0] == "department":
            raise HTTPException(400, "admin 不允许直接给部门;请改给 user 或 group")
    subject_kind, subject_id = chosen[0]

    from app.services.permissions import fmt_subject
    subject = fmt_subject(subject_kind, subject_id)  # type: ignore[arg-type]
    await permissions.add_project_subject(
        project_id=str(project_id), subject=subject, role=role,  # type: ignore[arg-type]
    )

    await audit.write(
        event_type="project_member_added",
        actor_user_id=user_id, target_project_id=project_id,
        details={"subject": subject, "role": role, "kind": subject_kind},
        **ctx,
    )


@router.delete("/{project_id}/members", status_code=204)
async def remove_project_member(
    project_id: uuid.UUID,
    subject: str = Query(..., description="完整 OpenFGA subject"),
    role: str = Query(..., pattern=r"^(admin|viewer|downloader|uploader)$"),
    db: AsyncSession = Depends(get_db),
    permissions: PermissionsService = Depends(get_permissions),
    audit: AuditService = Depends(get_audit),
    user: CurrentUser = Depends(get_current_user),
    is_system_admin: bool = Depends(get_is_system_admin),
    ctx: dict = Depends(get_request_context),
) -> None:
    user_id, user_open_id = user.id, user.open_id
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "project not found")
    await _enforce_project_admin(
        permissions, audit, user_id, user_open_id, project_id, "remove_member", ctx,
        is_system_admin=is_system_admin,
    )

    # admin 不变量(#106 修复):防止 admin 自我锁死 + 项目归零无 admin
    # (b) 不允许 admin 撤销自己的 admin 角色 — 必须先邀请其他 admin 再让别人撤销自己
    # (a) 不允许撤销后项目 admin 归零(兜底:group-admin 间接 user 也计入,接受 OpenFGA
    #     list_users 透传 leaf users 的语义 — 不完美但能拦住典型死循环路径)
    if role == "admin":
        if subject == f"user:{user_open_id}":
            raise HTTPException(
                409,
                "不允许撤销自己的项目管理员角色;请先邀请其他管理员,再让对方撤销你",
            )
        current_admins = await permissions.list_users_with_relation(
            object_type="project", object_id=str(project_id), relation="admin",
        )
        if len(current_admins) <= 1:
            raise HTTPException(
                409,
                "项目至少需要保留 1 个管理员;请先邀请其他管理员,再撤销当前管理员",
            )

    await permissions.remove_project_subject(
        project_id=str(project_id), subject=subject, role=role,  # type: ignore[arg-type]
    )

    await audit.write(
        event_type="project_member_removed",
        actor_user_id=user_id, target_project_id=project_id,
        details={"subject": subject, "role": role},
        **ctx,
    )
