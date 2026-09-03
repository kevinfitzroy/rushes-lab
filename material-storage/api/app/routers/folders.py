"""folders router — Phase B-2 iter7。

endpoints:
  POST   /api/v1/folders                          — 创建 folder(+bootstrap_folder OpenFGA)
                                                    需 can_edit project
  GET    /api/v1/folders?project_id=...           — 列表 user 可见的 folder
                                                    (普通 folder by project member +
                                                     sensitive_folder by list_objects can_view)
  GET    /api/v1/folders/{id}                     — 单条(can_view)
  DELETE /api/v1/folders/{id}                     — 删除空 folder(硬删;
                                                    普通夹 can_upload / sensitive 夹 can_admin)
  POST   /api/v1/folders/{id}/invite              — sensitive_folder 邀请(can_admin only)
  DELETE /api/v1/folders/{id}/invite/user/{uid}   — 撤销(can_admin only)
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.tables import Asset, Folder, Project
from app.deps import (
    get_audit,
    CurrentUser,
    get_current_user,
    get_is_system_admin,
    get_permissions,
    get_request_context,
)
from app.models import FolderCreateIn, FolderInviteIn, FolderOut
from app.services.audit import AuditService
from app.services.notifications import run_notify_folder_invite_bg
from app.services.permissions import PermissionsService, is_already_exists_error

log = logging.getLogger(__name__)
router = APIRouter()


def _parse_uuids(ids: list[str]) -> list[uuid.UUID]:
    """subject_id 字符串 → UUID,容错非法值(老 open_id 存量数据)直接跳过。"""
    out: list[uuid.UUID] = []
    for s in ids:
        try:
            out.append(uuid.UUID(s))
        except ValueError:
            continue
    return out


@router.post("", response_model=FolderOut, status_code=201)
async def create_folder(
    payload: FolderCreateIn,
    db: AsyncSession = Depends(get_db),
    permissions: PermissionsService = Depends(get_permissions),
    audit: AuditService = Depends(get_audit),
    user: CurrentUser = Depends(get_current_user),
    is_system_admin: bool = Depends(get_is_system_admin),
    ctx: dict = Depends(get_request_context),
) -> FolderOut:
    user_id = user.id
    # 1) 权限:create folder 需 can_upload(model v4:uploader 隐含创建子目录)
    #    - 在 project 下建 root folder → check project.can_upload
    #    - 在 folder 下建 sub folder → check parent folder.can_upload
    #    系统 admin 直通
    if payload.parent_folder_id:
        parent_folder_for_check = await db.get(Folder, payload.parent_folder_id)
        if not parent_folder_for_check or parent_folder_for_check.project_id != payload.project_id:
            raise HTTPException(400, "parent_folder invalid for this project")
        # sensitive folder 限只能挂 project 一级,sub folder 必须挂普通 folder
        check_type = "sensitive_folder" if parent_folder_for_check.is_sensitive else "folder"
        check_id = str(parent_folder_for_check.id)
    else:
        check_type = "project"
        check_id = str(payload.project_id)

    allowed = is_system_admin or await permissions.check(
        user_subject=user.subject,
        relation="can_upload",
        object_type=check_type,
        object_id=check_id,
    )
    if not allowed:
        await audit.write(
            event_type="access_denied",
            actor_user_id=user_id,
            target_project_id=payload.project_id,
            details={"action": "create_folder", "reason": "openfga can_upload false"},
            **ctx,
        )
        raise HTTPException(403, "no permission to create folder here(需 can_upload)")

    # 业务层 enforce:sensitive folder 只能直挂 project(限一级)
    if payload.is_sensitive and payload.parent_folder_id is not None:
        raise HTTPException(400, "sensitive folder 只能直挂 project 一级")

    # 2) 计算 minio_prefix
    minio_prefix = payload.minio_prefix
    if not minio_prefix:
        if payload.parent_folder_id:
            parent = await db.get(Folder, payload.parent_folder_id)
            assert parent is not None
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
        if "uq_folder_project_prefix" in str(e.orig):
            raise HTTPException(409, "该项目下已存在同名文件夹") from e
        raise HTTPException(400, "folder 创建失败,可能存在路径冲突") from e

    # 3) bootstrap OpenFGA parent tuple
    if payload.is_sensitive:
        # sensitive folder 必直挂 project(已 enforce)
        await permissions.bootstrap_sensitive_folder(
            folder_id=str(folder.id), project_id=str(payload.project_id),
        )
        # 自动给创建者永久 invited_downloader(隐含 can_view + can_download + can_upload)
        # — sensitive model 不让 admin 隐式 can_view,创建者若无显式 invite 会看不到自建 folder(#87)
        await permissions.invite_to_sensitive_folder(
            sensitive_folder_id=str(folder.id),
            subject=user.subject,
            level="downloader",
            duration_seconds=None,
        )
    else:
        # 普通 folder:可 nested,parent 是 project 或 folder
        if payload.parent_folder_id:
            parent_type: Literal["project", "folder"] = "folder"
            parent_id = str(payload.parent_folder_id)
        else:
            parent_type = "project"
            parent_id = str(payload.project_id)
        await permissions.bootstrap_folder(
            folder_id=str(folder.id),
            parent_type=parent_type,
            parent_id=parent_id,
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
    user: CurrentUser = Depends(get_current_user),
    is_system_admin: bool = Depends(get_is_system_admin),
) -> list[FolderOut]:
    # project 可见 check(public 直通,否则 can_view);系统 admin 直通
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "project not found")
    if not is_system_admin and project.visibility != "public":
        allowed = await permissions.check(
            user_subject=user.subject, relation="can_view",
            object_type="project", object_id=str(project_id),
        )
        if not allowed:
            raise HTTPException(403, "no permission")

    # 普通 folder:project member 都可见(用 SQL 拿全部)
    # sensitive folder:系统 admin 直接全部;否则 OpenFGA list_objects(can_view, sensitive_folder) intersect
    if is_system_admin:
        stmt = select(Folder).where(Folder.project_id == project_id).order_by(Folder.minio_prefix)
    else:
        sensitive_ids_str = await permissions.list_objects(
            user_subject=user.subject, relation="can_view", object_type="sensitive_folder"
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
    user: CurrentUser = Depends(get_current_user),
    is_system_admin: bool = Depends(get_is_system_admin),
) -> FolderOut:
    folder = await db.get(Folder, folder_id)
    if not folder:
        raise HTTPException(404, "folder not found")
    obj_type = "sensitive_folder" if folder.is_sensitive else "folder"

    if is_system_admin:
        can_view = can_download = can_upload = can_admin = True
    else:
        # public 项目非敏感 folder:组织内可浏览(「公开」语义,与 assets 列表 /
        # thumbnail-url 的"信任组织内可见性"一致);下载/上传/删除仍走各自权限
        public_browse = False
        if not folder.is_sensitive:
            project = await db.get(Project, folder.project_id)
            public_browse = project is not None and project.visibility == "public"

        async def _c(rel: str) -> bool:
            if rel == "can_view" and public_browse:
                return True
            return await permissions.check(
                user_subject=user.subject, relation=rel,
                object_type=obj_type, object_id=str(folder.id),
            )
        can_view, can_download, can_upload, can_admin = await asyncio.gather(
            _c("can_view"), _c("can_download"), _c("can_upload"), _c("can_admin"),
        )

    if not can_view:
        raise HTTPException(403, "no permission")
    out = FolderOut.model_validate(folder)
    out.my_can_view = can_view
    out.my_can_download = can_download
    out.my_can_upload = can_upload
    out.my_can_admin = can_admin
    return out


@router.delete("/{folder_id}", status_code=204)
async def delete_folder(
    folder_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    permissions: PermissionsService = Depends(get_permissions),
    audit: AuditService = Depends(get_audit),
    user: CurrentUser = Depends(get_current_user),
    is_system_admin: bool = Depends(get_is_system_admin),
    ctx: dict = Depends(get_request_context),
) -> None:
    """删除文件夹 — 仅允许空文件夹,硬删(ROADMAP D iter2 一期)。

    不做软删的原因:空文件夹无对象可延迟清理、重建成本一次点击,软删无收益;
    且 uq_folder_project_prefix 是全量唯一约束,软删占位会让同名重建撞 409。
    非空拒绝而非级联:assets.folder_id 是 RESTRICT,且子树删除的产品语义未定。

    空 = 无子文件夹 且 无资产行(含软删 —— 软删行仍占 RESTRICT FK)。
    权限:普通 folder 用 can_upload(与创建对称,uploader 自主管理目录结构,
    model 里 uploader 隐含建子目录);sensitive folder 维持 can_admin ——
    sensitive 的 can_upload 实为 downloader 级(model v4),拿它当删除门槛太宽,
    且邀请配置价值高。系统 admin 直通。OpenFGA tuple(parent / explicit_* /
    invited_*)尽力清理,失败不阻塞 DB 删除(孤儿 tuple 随 UUID 不复用而天然
    失效,同 directory 删组惯例)。
    """
    user_id = user.id
    folder = await db.get(Folder, folder_id)
    if not folder:
        raise HTTPException(404, "folder not found")

    obj_type = "sensitive_folder" if folder.is_sensitive else "folder"
    del_relation = "can_admin" if folder.is_sensitive else "can_upload"
    allowed = is_system_admin or await permissions.check(
        user_subject=user.subject, relation=del_relation,
        object_type=obj_type, object_id=str(folder_id),
    )
    if not allowed:
        await audit.write(
            event_type="access_denied",
            actor_user_id=user_id,
            target_project_id=folder.project_id,
            details={"action": "delete_folder", "folder_id": str(folder_id),
                     "reason": f"openfga {del_relation} false"},
            **ctx,
        )
        raise HTTPException(403, "no permission to delete this folder")

    child_id = await db.scalar(
        select(Folder.id).where(Folder.parent_folder_id == folder_id).limit(1)
    )
    if child_id is not None:
        raise HTTPException(409, "文件夹下还有子文件夹,请先删除子文件夹")
    asset_id = await db.scalar(
        select(Asset.id).where(Asset.folder_id == folder_id).limit(1)
    )
    if asset_id is not None:
        raise HTTPException(
            409, "文件夹不为空(可能含已软删的文件),请先彻底清空后再删除"
        )

    # OpenFGA tuple 清理:该 object 上的所有 tuple(parent + explicit_* / invited_*)
    try:
        from openfga_sdk.client.models import ClientTuple, ClientWriteRequest
        from openfga_sdk.models import ReadRequestTupleKey
        resp = await permissions._client.read(  # type: ignore[attr-defined]
            ReadRequestTupleKey(object=f"{obj_type}:{folder_id}")
        )
        for t in resp.tuples:
            try:
                await permissions._client.write(  # type: ignore[attr-defined]
                    ClientWriteRequest(deletes=[ClientTuple(
                        user=t.key.user, relation=t.key.relation, object=t.key.object,
                    )])
                )
            except Exception:
                log.debug("folder tuple delete tolerate %s %s %s",
                          t.key.user, t.key.relation, t.key.object)
    except Exception as e:
        log.warning("delete folder tuple cleanup fail folder=%s err=%s", folder_id, e)

    name, prefix, is_sensitive, project_id = (
        folder.name, folder.minio_prefix, folder.is_sensitive, folder.project_id,
    )
    await db.delete(folder)
    await db.commit()
    await audit.write(
        event_type="folder_deleted",
        actor_user_id=user_id,
        target_project_id=project_id,
        details={
            "folder_id": str(folder_id),
            "name": name,
            "minio_prefix": prefix,
            "is_sensitive": is_sensitive,
        },
        **ctx,
    )
    log.info("folder deleted id=%s name=%s sensitive=%s by user=%s",
             folder_id, name, is_sensitive, user_id)


@router.post("/{folder_id}/invite", status_code=204)
async def invite(
    folder_id: uuid.UUID,
    payload: FolderInviteIn,
    background: BackgroundTasks,  # #153:应用内邀请通知用(#162 下线 IM 后原任务移除,参数重新引入)
    db: AsyncSession = Depends(get_db),
    permissions: PermissionsService = Depends(get_permissions),
    audit: AuditService = Depends(get_audit),
    user: CurrentUser = Depends(get_current_user),
    is_system_admin: bool = Depends(get_is_system_admin),
    ctx: dict = Depends(get_request_context),
) -> None:
    """邀请 user / group 进入 sensitive_folder(admin 操作)。

    审批驱动的邀请走 /api/v1/approvals。#154:department 轴写入已下线(ADR-0007)。"""
    user_id = user.id
    folder = await db.get(Folder, folder_id)
    if not folder:
        raise HTTPException(404, "folder not found")
    if not folder.is_sensitive:
        raise HTTPException(400, "only sensitive_folder needs invite")

    # subject 二选一(普通 OR 排除,只允许一个非 None)
    provided = [
        ("user", payload.user_id),
        ("group", payload.group_id),
    ]
    chosen = [(k, v) for k, v in provided if v]
    if len(chosen) != 1:
        raise HTTPException(400, "must specify exactly one of user_id / group_id")
    subject_kind, subject_id = chosen[0]

    # admin check;系统 admin 直通
    allowed = is_system_admin or await permissions.check(
        user_subject=user.subject, relation="can_admin",
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

    from app.services.permissions import fmt_subject
    subject = fmt_subject(subject_kind, str(subject_id))  # type: ignore[arg-type]
    await permissions.invite_to_sensitive_folder(
        sensitive_folder_id=str(folder_id),
        subject=subject,
        level=payload.level,  # type: ignore[arg-type]
        duration_seconds=payload.duration_seconds,
    )

    await audit.write(
        event_type="sensitive_folder_invited",
        actor_user_id=user_id,
        target_project_id=folder.project_id,
        details={
            "folder_id": str(folder_id),
            "subject": subject,
            "level": payload.level,
            "permanent": payload.duration_seconds is None,
            "duration_seconds": payload.duration_seconds,
        },
        **ctx,
    )


    # #153:应用内"目录邀请"通知 — 仅 user 类型推送(group/department 无对应用户);
    # #162 已下线 IM 卡片,此为唯一通知渠道
    if subject_kind == "user":
        # #148:subject_id 已是 users.id UUID,直接主键查
        from app.db.tables import User as _User
        invitee = await db.get(_User, uuid.UUID(str(subject_id)))
        if invitee is not None:
            background.add_task(
                run_notify_folder_invite_bg,
                folder_id=folder_id,
                invitee_user_id=invitee.id,
                inviter_user_id=user_id,
                duration_seconds=payload.duration_seconds,
            )

@router.get("/{folder_id}/members")
async def list_members(
    folder_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    permissions: PermissionsService = Depends(get_permissions),
    user: CurrentUser = Depends(get_current_user),
    is_system_admin: bool = Depends(get_is_system_admin),
) -> list[dict]:
    """sensitive_folder 当前成员列表 — D iter3 前端 FolderInvitePanel 用。

    返:[{subject, kind, name, level, permanent, expires_at?}]
    subject 形如 "user:<users.id UUID>" / "group:<gid>#member" / "department:<did>#member"
    需 can_admin folder;系统 admin 直通。
    """
    folder = await db.get(Folder, folder_id)
    if not folder:
        raise HTTPException(404, "folder not found")
    if not folder.is_sensitive:
        raise HTTPException(400, "not a sensitive_folder")

    allowed = is_system_admin or await permissions.check(
        user_subject=user.subject, relation="can_admin",
        object_type="sensitive_folder", object_id=str(folder_id),
    )
    if not allowed:
        raise HTTPException(403, "no admin permission")

    # OpenFGA read 所有 tuples for sensitive_folder:<id>
    from openfga_sdk.models import ReadRequestTupleKey
    from app.db.tables import User as _User
    resp = await permissions._client.read(  # type: ignore[attr-defined]
        ReadRequestTupleKey(object=f"sensitive_folder:{folder_id}")
    )

    members: list[dict] = []
    user_subject_ids: list[str] = []
    user_records: list[dict] = []   # 后面合并 db 名

    INVITE_RELATIONS = {
        "invited_viewer":            ("viewer", True),
        "invited_downloader":        ("downloader", True),
        "explicit_invited_viewer":   ("viewer", False),
        "explicit_invited_downloader": ("downloader", False),
    }
    for t in resp.tuples:
        rel = t.key.relation
        if rel not in INVITE_RELATIONS:
            continue
        level, permanent = INVITE_RELATIONS[rel]
        subject = t.key.user            # e.g. "user:ou_xxx" or "group:gid#member"
        kind, rest = subject.split(":", 1)
        sid = rest.rsplit("#", 1)[0]    # 去 #member 后缀

        expires_at = None
        cond = getattr(t.key, "condition", None)
        if cond and not permanent:
            try:
                ctx = cond.context or {}
                gt = ctx.get("grant_time")
                dur = ctx.get("grant_duration", "0s")
                if gt:
                    from datetime import datetime, timedelta
                    seconds = int(dur.rstrip("s"))
                    expires_at = (
                        datetime.fromisoformat(gt.replace("Z", "+00:00"))
                        + timedelta(seconds=seconds)
                    ).isoformat()
            except (ValueError, AttributeError):
                pass

        record = {
            "subject": subject,
            "kind": kind,            # user / group / department
            "subject_id": sid,
            "name": None,            # 后面 db 查
            "level": level,
            "permanent": permanent,
            "expires_at": expires_at,
        }
        if kind == "user":
            user_subject_ids.append(sid)
            user_records.append(record)
        else:
            # group / department:目前没拉 db,显示 id
            record["name"] = f"{('用户组' if kind == 'group' else '部门')} {sid[:12]}…"
            members.append(record)

    # user 批量查 db 拿 name(subject_id = users.id UUID 字符串,容错非法值)
    if user_subject_ids:
        stmt = select(_User).where(_User.id.in_(_parse_uuids(user_subject_ids)))
        res = await db.execute(stmt)
        name_by_user_id = {str(u.id): u.name for u in res.scalars().all()}
        for r in user_records:
            r["name"] = name_by_user_id.get(r["subject_id"], r["subject_id"][:12] + "…")
        members.extend(user_records)

    # 排序:user 在前,group/department 在后;name 字典序
    members.sort(key=lambda m: (0 if m["kind"] == "user" else 1, m["name"] or ""))
    return members


@router.delete("/{folder_id}/invite", status_code=204)
async def revoke_invite(
    folder_id: uuid.UUID,
    subject: str = Query(..., description="完整 subject 字符串,例:user:<users.id UUID> / group:<gid>#member / department:<did>#member"),
    level: str = Query("viewer", pattern=r"^(viewer|downloader)$"),
    permanent: bool = Query(True, description="True=删 invited(永久);False=删 explicit_invited(临时)"),
    db: AsyncSession = Depends(get_db),
    permissions: PermissionsService = Depends(get_permissions),
    audit: AuditService = Depends(get_audit),
    user: CurrentUser = Depends(get_current_user),
    is_system_admin: bool = Depends(get_is_system_admin),
    ctx: dict = Depends(get_request_context),
) -> None:
    user_id = user.id
    folder = await db.get(Folder, folder_id)
    if not folder:
        raise HTTPException(404, "folder not found")
    if not folder.is_sensitive:
        raise HTTPException(400, "not a sensitive_folder")

    allowed = is_system_admin or await permissions.check(
        user_subject=user.subject, relation="can_admin",
        object_type="sensitive_folder", object_id=str(folder_id),
    )
    if not allowed:
        raise HTTPException(403, "no admin permission")

    await permissions.revoke_sensitive_folder_invite(
        sensitive_folder_id=str(folder_id),
        subject=subject,
        level=level,  # type: ignore[arg-type]
        permanent=permanent,
    )

    await audit.write(
        event_type="sensitive_folder_revoked",
        actor_user_id=user_id,
        target_project_id=folder.project_id,
        details={
            "folder_id": str(folder_id),
            "subject": subject,
            "level": level,
            "permanent": permanent,
        },
        **ctx,
    )


# ─── 普通 folder explicit grant(仅一级 folder)─────────────────────────────
FOLDER_GRANT_KINDS = ("viewer", "downloader", "uploader")


def _enforce_level1_folder(folder: Folder) -> None:
    if folder.parent_folder_id is not None:
        raise HTTPException(
            400,
            "explicit grant 仅支持一级 folder(直接挂在 project 下);"
            "深层 folder 想要不同权限,请在 project 下新建一级 folder",
        )


@router.get("/{folder_id}/grants")
async def list_folder_grants(
    folder_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    permissions: PermissionsService = Depends(get_permissions),
    user: CurrentUser = Depends(get_current_user),
    is_system_admin: bool = Depends(get_is_system_admin),
) -> list[dict]:
    """列普通 folder 的 explicit_* grants。

    返:[{subject, kind, subject_id, name, role: explicit_viewer|downloader|uploader}]
    需 can_admin folder + folder 为一级;系统 admin 直通。
    """
    folder = await db.get(Folder, folder_id)
    if folder is None:
        raise HTTPException(404, "folder not found")
    if folder.is_sensitive:
        raise HTTPException(400, "sensitive folder 用 /members endpoint")
    _enforce_level1_folder(folder)

    allowed = is_system_admin or await permissions.check(
        user_subject=user.subject, relation="can_admin",
        object_type="folder", object_id=str(folder_id),
    )
    if not allowed:
        raise HTTPException(403, "no admin permission on this folder")

    from openfga_sdk.models import ReadRequestTupleKey
    from app.db.tables import User as _User
    resp = await permissions._client.read(  # type: ignore[attr-defined]
        ReadRequestTupleKey(object=f"folder:{folder_id}")
    )

    grants: list[dict] = []
    user_subject_ids: list[str] = []
    user_rows: list[dict] = []
    GRANT_RELATIONS = {f"explicit_{k}" for k in FOLDER_GRANT_KINDS}
    for t in resp.tuples:
        rel = t.key.relation
        if rel not in GRANT_RELATIONS:
            continue
        kind = rel.removeprefix("explicit_")  # viewer / downloader / uploader
        subject = t.key.user
        sk, rest = subject.split(":", 1)
        sid = rest.rsplit("#", 1)[0]
        rec = {
            "subject": subject, "kind": sk, "subject_id": sid,
            "name": None, "level": kind,
        }
        if sk == "user":
            user_subject_ids.append(sid)
            user_rows.append(rec)
        else:
            label = "用户组" if sk == "group" else "部门"
            rec["name"] = f"{label} {sid[:12]}…"
            grants.append(rec)

    if user_subject_ids:
        stmt = select(_User).where(_User.id.in_(_parse_uuids(user_subject_ids)))
        res = await db.execute(stmt)
        name_by = {str(u.id): u.name for u in res.scalars().all()}
        for r in user_rows:
            r["name"] = name_by.get(r["subject_id"], r["subject_id"][:12] + "…")
        grants.extend(user_rows)

    grants.sort(key=lambda g: (0 if g["kind"] == "user" else 1, g["name"] or ""))
    return grants


@router.post("/{folder_id}/grants", status_code=204)
async def add_folder_grant(
    folder_id: uuid.UUID,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    permissions: PermissionsService = Depends(get_permissions),
    audit: AuditService = Depends(get_audit),
    user: CurrentUser = Depends(get_current_user),
    is_system_admin: bool = Depends(get_is_system_admin),
    ctx: dict = Depends(get_request_context),
) -> None:
    """body:{user_id|group_id, level?: viewer|downloader|uploader, levels?: [...]}
    levels 一次授多 level;旧单 level 字段继续兼容
    (user_id = users.id UUID,#148 起;#154:department 轴写入下线)"""
    user_id = user.id
    folder = await db.get(Folder, folder_id)
    if folder is None:
        raise HTTPException(404, "folder not found")
    if folder.is_sensitive:
        raise HTTPException(400, "sensitive folder 用 /invite endpoint")
    _enforce_level1_folder(folder)

    allowed = is_system_admin or await permissions.check(
        user_subject=user.subject, relation="can_admin",
        object_type="folder", object_id=str(folder_id),
    )
    if not allowed:
        raise HTTPException(403, "no admin permission on this folder")

    # P2-1:levels 类型先校验(客户端误传字符串时按字符迭代,报错费解)
    raw_levels = payload.get("levels")
    if raw_levels is not None and not isinstance(raw_levels, list):
        raise HTTPException(400, "levels 必须是数组")
    legacy_level = payload.get("level")
    raw_levels = raw_levels or ([legacy_level] if legacy_level else [])
    bad = [l for l in raw_levels if not isinstance(l, str) or l not in FOLDER_GRANT_KINDS]
    if bad:
        raise HTTPException(400, f"level must be one of {FOLDER_GRANT_KINDS}: got {bad}")
    if not raw_levels:
        raise HTTPException(400, "level(或 levels)必填")
    levels = [l for l in FOLDER_GRANT_KINDS if l in set(raw_levels)]  # 去重 + 固定序

    provided = [
        ("user", payload.get("user_id")),
        ("group", payload.get("group_id")),
    ]
    chosen = [(k, v) for k, v in provided if v]
    if len(chosen) != 1:
        raise HTTPException(
            400, "must specify exactly one of user_id / group_id"
        )
    subject_kind, subject_id = chosen[0]

    from app.services.permissions import fmt_subject
    subject = fmt_subject(subject_kind, str(subject_id))  # type: ignore[arg-type]
    # 部分成功语义:重复(已存在)按幂等跳过;真错误中止 —— 此前 level 已生效并
    # 留有 audit,客户端重试可幂等补齐(P2-2)。注意 folder grant 由服务层内部
    # 先删后写刷新到期时间(grant_folder_explicit_subject),不会走到这里。
    for level in levels:
        try:
            await permissions.grant_folder_explicit_subject(
                folder_id=str(folder_id), subject=subject,
                kind=f"explicit_{level}",  # type: ignore[arg-type]
            )
        except Exception as e:
            # OpenFGA 重复 tuple —— 重复 grant / 多 level 部分重叠按幂等成功跳过;
            # 真错误继续抛
            if not is_already_exists_error(e):
                raise
            continue
        await audit.write(
            event_type="folder_grant_added",
            actor_user_id=user_id, target_project_id=folder.project_id,
            details={"folder_id": str(folder_id), "subject": subject, "level": level},
            **ctx,
        )


@router.delete("/{folder_id}/grants", status_code=204)
async def remove_folder_grant(
    folder_id: uuid.UUID,
    subject: str = Query(..., description="完整 OpenFGA subject"),
    level: str = Query(..., pattern=r"^(viewer|downloader|uploader)$"),
    db: AsyncSession = Depends(get_db),
    permissions: PermissionsService = Depends(get_permissions),
    audit: AuditService = Depends(get_audit),
    user: CurrentUser = Depends(get_current_user),
    is_system_admin: bool = Depends(get_is_system_admin),
    ctx: dict = Depends(get_request_context),
) -> None:
    user_id = user.id
    folder = await db.get(Folder, folder_id)
    if folder is None:
        raise HTTPException(404, "folder not found")
    if folder.is_sensitive:
        raise HTTPException(400, "sensitive folder 用 /invite endpoint")
    _enforce_level1_folder(folder)

    allowed = is_system_admin or await permissions.check(
        user_subject=user.subject, relation="can_admin",
        object_type="folder", object_id=str(folder_id),
    )
    if not allowed:
        raise HTTPException(403, "no admin permission on this folder")

    await permissions.revoke_folder_explicit_subject(
        folder_id=str(folder_id), subject=subject,
        kind=f"explicit_{level}",  # type: ignore[arg-type]
    )
    await audit.write(
        event_type="folder_grant_removed",
        actor_user_id=user_id, target_project_id=folder.project_id,
        details={"folder_id": str(folder_id), "subject": subject, "level": level},
        **ctx,
    )
