"""assets router — uppy 5-endpoint + list + download + iter4 enforce + audit。

Phase B-2 iter4:每 endpoint 加 OpenFGA check + audit 落库。
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import ColumnElement, func, literal, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.tables import Asset, Folder, Project
from app.deps import (
    CurrentUser,
    get_audit,
    get_current_user,
    get_is_system_admin,
    get_permissions,
    get_presign,
    get_request_context,
)
from app.models import (
    AssetMetaUpdateIn,
    AssetOut,
    DownloadLinkOut,
    SearchResultOut,
    UploadCompleteIn,
    UploadMultipartCreateOut,
    UploadPartUrlOut,
    UploadUrlRequest,
)
from app.services.audit import AuditService, mint_trace_id
from app.services.permissions import PermissionsService
from app.services.presign import PresignService
from app.settings import get_settings

router = APIRouter()


# ─── multipart upload(uppy AwsS3 plugin)─────────────────────────────────────
@router.post("/uploads", response_model=UploadMultipartCreateOut)
async def create_upload(
    payload: UploadUrlRequest,
    db: AsyncSession = Depends(get_db),
    permissions: PermissionsService = Depends(get_permissions),
    presign: PresignService = Depends(get_presign),
    audit: AuditService = Depends(get_audit),
    user: CurrentUser = Depends(get_current_user),
    is_system_admin: bool = Depends(get_is_system_admin),
    ctx: dict = Depends(get_request_context),
) -> UploadMultipartCreateOut:
    user_id = user.id
    folder = await db.get(Folder, payload.folder_id)
    if not folder:
        raise HTTPException(404, "folder not found")

    # check can_upload folder(v4:uploader 隐含上传 + 创建 sub folder);系统 admin 直通
    allowed = is_system_admin or await permissions.check(
        user_subject=user.subject,
        relation="can_upload",
        object_type="folder" if not folder.is_sensitive else "sensitive_folder",
        object_id=str(folder.id),
    )
    if not allowed:
        await audit.write(
            event_type="access_denied",
            actor_user_id=user_id,
            target_project_id=folder.project_id,
            details={"action": "create_upload", "folder_id": str(folder.id),
                     "filename": payload.filename, "reason": "openfga can_edit false"},
            **ctx,
        )
        raise HTTPException(403, "no permission to upload to this folder")

    key = f"{folder.minio_prefix.rstrip('/')}/{payload.filename}"
    bucket = await _project_bucket(db, folder.project_id)

    upload_id = presign.create_multipart_upload(bucket, key, payload.content_type)
    return UploadMultipartCreateOut(upload_id=upload_id, key=key, bucket=bucket)


@router.get("/uploads/{upload_id}/parts/{part_number}", response_model=UploadPartUrlOut)
async def sign_part(
    upload_id: str,
    part_number: int,
    bucket: str = Query(...),
    key: str = Query(...),
    presign: PresignService = Depends(get_presign),
    user: CurrentUser = Depends(get_current_user),  # 至少要认证;细粒度上传 check 在 create_upload 已做
) -> UploadPartUrlOut:
    settings = get_settings()
    url = presign.sign_part_url(
        bucket, key, upload_id, part_number,
        expires_seconds=settings.presigned_normal_ttl_seconds,
    )
    return UploadPartUrlOut(url=url, expires_in=settings.presigned_normal_ttl_seconds)


@router.post("/uploads/{upload_id}/complete", response_model=AssetOut)
async def complete_upload(
    upload_id: str,
    payload: UploadCompleteIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    permissions: PermissionsService = Depends(get_permissions),
    presign: PresignService = Depends(get_presign),
    audit: AuditService = Depends(get_audit),
    user: CurrentUser = Depends(get_current_user),
    is_system_admin: bool = Depends(get_is_system_admin),
    ctx: dict = Depends(get_request_context),
) -> AssetOut:
    user_id = user.id
    folder_id = await _resolve_folder_by_key(db, payload.bucket, payload.key)
    if not folder_id:
        raise HTTPException(400, detail=f"folder for key {payload.key} not found")

    folder = await db.get(Folder, folder_id)
    if not folder:
        raise HTTPException(500, "folder lookup race")

    # 再次 check(防 user create_upload 后被 revoke);系统 admin 直通
    allowed = is_system_admin or await permissions.check(
        user_subject=user.subject,
        relation="can_upload",
        object_type="folder" if not folder.is_sensitive else "sensitive_folder",
        object_id=str(folder.id),
    )
    if not allowed:
        # 撤销半成品 multipart
        presign.abort_multipart_upload(payload.bucket, payload.key, upload_id)
        raise HTTPException(403, "no permission to complete upload(可能权限被撤销)")

    result = presign.complete_multipart_upload(
        payload.bucket, payload.key, upload_id, payload.parts  # type: ignore[arg-type]
    )

    # head_object 拿真实 size + content-type(complete 返回不含)
    head = presign.head_object(payload.bucket, payload.key)

    asset = Asset(
        id=uuid.uuid4(),
        folder_id=folder_id,
        filename=payload.key.rsplit("/", 1)[-1],
        minio_bucket=payload.bucket,
        minio_key=payload.key,
        etag=head.get("etag") or result.get("etag"),
        minio_version_id=head.get("version_id") or result.get("version_id"),
        size_bytes=head.get("size_bytes") or 0,
        content_type=head.get("content_type"),
        uploader_id=user_id,
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)

    await permissions.bootstrap_asset(
        asset_id=str(asset.id),
        parent_type="sensitive_folder" if folder.is_sensitive else "folder",
        parent_id=str(folder.id),
    )

    trace_id = mint_trace_id()
    await audit.upload(
        actor_user_id=user_id,
        target_asset_id=asset.id,
        target_project_id=folder.project_id,
        target_minio_key=payload.key,
        dedup_key=f"upload:{asset.id}",
        trace_id=trace_id,
        details={
            "size_bytes": asset.size_bytes,
            "etag": asset.etag,
            "version_id": asset.minio_version_id,
            "parts": len(payload.parts),
        },
        **ctx,
    )

    # B-4:enqueue thumbnail 生成 — image 走 Pillow worker;video 走 ffmpeg worker (B-4 iter2 #101)
    ct = asset.content_type or ""
    if ct.startswith("image/"):
        from app.services.arq_pool import enqueue_thumbnail
        await enqueue_thumbnail(request.app.state.arq_pool, str(asset.id))
    elif ct.startswith("video/"):
        from app.services.arq_pool import enqueue_video_thumbnail
        await enqueue_video_thumbnail(request.app.state.arq_pool, str(asset.id))

    return AssetOut.model_validate(asset)


@router.delete("/uploads/{upload_id}", status_code=204)
async def abort_upload(
    upload_id: str,
    bucket: str = Query(...),
    key: str = Query(...),
    presign: PresignService = Depends(get_presign),
    user: CurrentUser = Depends(get_current_user),
) -> None:
    """主动 abort multipart;凡是认证 user 都可 abort 自己 upload。"""
    presign.abort_multipart_upload(bucket, key, upload_id)


# ─── list assets ──────────────────────────────────────────────────────────────
@router.get("", response_model=list[AssetOut])
async def list_assets(
    folder_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    permissions: PermissionsService = Depends(get_permissions),
    user: CurrentUser = Depends(get_current_user),
    is_system_admin: bool = Depends(get_is_system_admin),
    limit: int = 100,
    offset: int = 0,
) -> list[AssetOut]:
    folder = await db.get(Folder, folder_id)
    if not folder:
        raise HTTPException(404, "folder not found")

    # check can_view folder;系统 admin 直通
    allowed = is_system_admin or await permissions.check(
        user_subject=user.subject,
        relation="can_view",
        object_type="folder" if not folder.is_sensitive else "sensitive_folder",
        object_id=str(folder.id),
    )
    if not allowed:
        # 不暴露 folder 存在性,403 不写 audit(避免攻击者通过 audit 推断结构)
        raise HTTPException(403, "no permission")

    stmt = (
        select(Asset)
        .where(Asset.folder_id == folder_id, Asset.deleted_at.is_(None))
        .order_by(Asset.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    res = await db.execute(stmt)
    return [AssetOut.model_validate(r) for r in res.scalars().all()]


# ─── 盲搜(标签 + 跨 folder,#151)────────────────────────────────────────────
@router.get("/search", response_model=list[SearchResultOut])
async def search_assets(
    q: str = Query(..., min_length=1, max_length=200),
    db: AsyncSession = Depends(get_db),
    permissions: PermissionsService = Depends(get_permissions),
    user: CurrentUser = Depends(get_current_user),
    is_system_admin: bool = Depends(get_is_system_admin),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[SearchResultOut]:
    """跨 folder 盲搜:匹配文件名 / user_labels / notes。

    权限边界(本 endpoint 的硬约束):
    - 普通 user:先 `list_objects(can_view)` 取可达 folder(folder + sensitive_folder 两型),
      SQL 只查这些 folder 内的 asset —— sensitive 素材的存在性(名称/计数)零泄露。
    - 系统 admin 直通(SQL 全量,不查 OpenFGA)。
    - 注:asset 级 explicit_downloader(单文件临时 grant)不在此 folder 集合内,这类
      资产不会出现在搜索结果 —— 方向是保守(宁漏勿泄),可接受。

    搜索实现:PG ILIKE + pg_trgm 起步(百万行量级够用):
    - filename / notes 走 GIN trgm 索引(模糊子串)。
    - user_labels:精确元素 `q = ANY(...)`;模糊匹配走
      `array_to_string(user_labels, ' ') ILIKE` + GIN trgm 表达式索引
      (migration 0011)—— 单表达式索引即可命中,取代原先 unnest EXISTS(不可索引,
      且 SQLAlchemy 渲染出的列名 PG 不认,review F1/F8)。
    """
    q = q.strip()
    if not q:
        raise HTTPException(400, "q 不能为空")
    pattern = f"%{_escape_like(q)}%"

    # ColumnElement[bool]:系统 admin 直通 = 恒 true;否则 folder_id IN 可达集合
    folder_filter: ColumnElement[bool] = true()
    if not is_system_admin:
        folder_ids: list[uuid.UUID] = []
        for obj_type in ("folder", "sensitive_folder"):
            ids_str = await permissions.list_objects(
                user_subject=user.subject, relation="can_view", object_type=obj_type,
            )
            folder_ids.extend(uuid.UUID(s) for s in ids_str)
        if not folder_ids:
            return []  # 无可达 folder → 结果必为空,不跑 SQL
        folder_filter = Asset.folder_id.in_(folder_ids)

    # user_labels 精确元素匹配(q = ANY(array))
    label_exact = Asset.user_labels.any(literal(q))
    # user_labels 模糊匹配:整数组拼串后 ILIKE,命中 GIN trgm 表达式索引
    label_fuzzy = func.array_to_string(Asset.user_labels, " ").ilike(pattern, escape="\\")

    stmt = (
        select(Asset, Folder.name, Project.id, Project.name)
        .join(Folder, Asset.folder_id == Folder.id)
        .join(Project, Folder.project_id == Project.id)
        .where(
            Asset.deleted_at.is_(None),
            folder_filter,
            or_(
                Asset.filename.ilike(pattern, escape="\\"),
                Asset.notes.ilike(pattern, escape="\\"),
                label_exact,
                label_fuzzy,
            ),
        )
        .order_by(Asset.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    res = await db.execute(stmt)
    out: list[SearchResultOut] = []
    for asset, folder_name, project_id, project_name in res.all():
        data = AssetOut.model_validate(asset).model_dump()
        data.update(
            folder_name=folder_name,
            project_id=project_id,
            project_name=project_name,
        )
        out.append(SearchResultOut(**data))
    return out


# ─── 打标 / 改标(#151)────────────────────────────────────────────────────────
@router.patch("/{asset_id}/meta", response_model=AssetOut)
async def update_asset_meta(
    asset_id: uuid.UUID,
    payload: AssetMetaUpdateIn,
    db: AsyncSession = Depends(get_db),
    permissions: PermissionsService = Depends(get_permissions),
    audit: AuditService = Depends(get_audit),
    user: CurrentUser = Depends(get_current_user),
    is_system_admin: bool = Depends(get_is_system_admin),
    ctx: dict[str, Any] = Depends(get_request_context),
) -> AssetOut:
    """写 user_labels / notes(audit `asset.tag_updated`)。

    权限:can_upload 于父 folder(uploader 隐含编辑),或系统 admin 直通。
    """
    user_id = user.id
    asset = await db.get(Asset, asset_id)
    if not asset or asset.deleted_at is not None:
        raise HTTPException(404, "asset not found")
    folder = await db.get(Folder, asset.folder_id)
    if not folder:
        raise HTTPException(500, "asset folder lookup race")

    allowed = is_system_admin or await permissions.check(
        user_subject=user.subject,
        relation="can_upload",
        object_type="sensitive_folder" if folder.is_sensitive else "folder",
        object_id=str(folder.id),
    )
    if not allowed:
        await audit.write(
            event_type="access_denied",
            actor_user_id=user_id,
            target_asset_id=asset_id,
            target_project_id=folder.project_id,
            target_minio_key=asset.minio_key,
            details={"action": "update_asset_meta", "reason": "openfga can_upload false"},
            **ctx,
        )
        raise HTTPException(403, "no permission to edit this asset")

    if payload.user_labels is not None:
        asset.user_labels = _normalize_labels(payload.user_labels)
    if payload.notes is not None:
        asset.notes = payload.notes[:2000] if payload.notes else ""
    await db.commit()
    await db.refresh(asset)

    await audit.write(
        event_type="asset.tag_updated",
        actor_user_id=user_id,
        target_asset_id=asset_id,
        target_project_id=folder.project_id,
        target_minio_key=asset.minio_key,
        details={"user_labels": asset.user_labels, "notes": asset.notes},
        **ctx,
    )
    return AssetOut.model_validate(asset)


# ─── download link ────────────────────────────────────────────────────────────
@router.post("/{asset_id}/download-link", response_model=DownloadLinkOut)
async def get_download_link(
    asset_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    permissions: PermissionsService = Depends(get_permissions),
    presign: PresignService = Depends(get_presign),
    audit: AuditService = Depends(get_audit),
    user: CurrentUser = Depends(get_current_user),
    is_system_admin: bool = Depends(get_is_system_admin),
    ctx: dict = Depends(get_request_context),
) -> DownloadLinkOut:
    user_id = user.id
    """签 presigned GET URL;check can_download asset + audit signed_url_issued。
    系统 admin 直通(audit 仍记)。"""
    asset = await db.get(Asset, asset_id)
    if not asset:
        raise HTTPException(404, "asset not found")

    allowed = is_system_admin or await permissions.check(
        user_subject=user.subject,
        relation="can_download",
        object_type="asset",
        object_id=str(asset_id),
    )
    if not allowed:
        await audit.write(
            event_type="download_denied",
            actor_user_id=user_id,
            target_asset_id=asset_id,
            target_minio_key=asset.minio_key,
            details={"reason": "openfga can_download false"},
            **ctx,
        )
        raise HTTPException(403, "no permission to download(可申请审批)")

    settings = get_settings()
    ttl = settings.presigned_normal_ttl_seconds
    url = presign.sign_get_url(asset.minio_bucket, asset.minio_key, ttl)

    await audit.signed_url_issued(
        actor_user_id=user_id,
        target_asset_id=asset.id,
        target_minio_key=asset.minio_key,
        details={"expires_in_seconds": ttl},
        **ctx,
    )

    return DownloadLinkOut(url=url, expires_in=ttl, is_sensitive=False)


# ─── thumbnail URL — B-4 (轻量,签短 ttl presigned,不走 OpenFGA enforce)──────
@router.get("/{asset_id}/thumbnail-url")
async def get_thumbnail_url(
    asset_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    presign: PresignService = Depends(get_presign),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """缩略图 presigned URL — 至少要登录;不再做 per-asset OpenFGA check
    (缩略图 1024px 模糊化,信息密度低,信任组织内可见性)。

    无 thumbnail_key(还没生成 / 非图)→ 404。
    """
    _ = user.id  # 至少要认证
    asset = await db.get(Asset, asset_id)
    if asset is None or asset.deleted_at is not None:
        raise HTTPException(404, "asset not found")
    thumbnail_key = (asset.tags or {}).get("thumbnail_key")
    if not thumbnail_key:
        raise HTTPException(404, "no thumbnail yet(可能还在生成 / 非图片)")

    ttl = 1800   # 30 min — 缩略图比原图 ttl 长(让浏览器缓存有效)
    # ADR-0008 P1:缩略图走独立 bucket + 缩略图 MinIO(SSD);endpoint/bucket 由 env 控制
    url = presign.sign_thumbnail_url(thumbnail_key, ttl)
    return {"url": url, "expires_in": ttl}


# ─── delete(soft)──────────────────────────────────────────────────────────
@router.delete("/{asset_id}", status_code=204)
async def delete_asset(
    asset_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    permissions: PermissionsService = Depends(get_permissions),
    audit: AuditService = Depends(get_audit),
    user: CurrentUser = Depends(get_current_user),
    is_system_admin: bool = Depends(get_is_system_admin),
    ctx: dict = Depends(get_request_context),
) -> None:
    user_id = user.id
    """soft delete:置 deleted_at;MinIO object 保留(由 bucket lifecycle 异步清)。

    权限:asset.can_admin(model v4:= can_admin from parent folder/project);系统 admin 直通。
    """
    from datetime import datetime, timezone
    asset = await db.get(Asset, asset_id)
    if not asset:
        raise HTTPException(404, "asset not found")

    allowed = is_system_admin or await permissions.check(
        user_subject=user.subject, relation="can_admin",
        object_type="asset", object_id=str(asset_id),
    )
    if not allowed:
        await audit.write(
            event_type="access_denied", actor_user_id=user_id,
            target_asset_id=asset_id, target_minio_key=asset.minio_key,
            details={"action": "delete_asset", "reason": "openfga can_admin false"},
            **ctx,
        )
        raise HTTPException(403, "no delete permission")

    if asset.deleted_at is not None:
        return  # idempotent

    asset.deleted_at = datetime.now(timezone.utc)
    await db.commit()

    await audit.write(
        event_type="asset_deleted", actor_user_id=user_id,
        target_asset_id=asset_id, target_minio_key=asset.minio_key,
        details={"filename": asset.filename, "soft": True},
        **ctx,
    )


# ─── helpers ──────────────────────────────────────────────────────────────────
_MAX_LABELS = 50
_MAX_LABEL_LEN = 64  # 与 tables.assets.user_labels ARRAY(String(64)) 对齐


def _escape_like(q: str) -> str:
    """转义 ILIKE 通配符(%, _, 反斜杠),让 q 按字面匹配。"""
    return q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _normalize_labels(labels: list[str]) -> list[str]:
    """trim + 去空 + 截断超长 + 去重,上限 _MAX_LABELS 个(防止滥用撑爆 token 预算)。"""
    out: list[str] = []
    seen: set[str] = set()
    for raw in labels:
        label = raw.strip()
        if not label:
            continue
        if len(label) > _MAX_LABEL_LEN:
            label = label[:_MAX_LABEL_LEN]
        if label in seen:
            continue
        seen.add(label)
        out.append(label)
        if len(out) >= _MAX_LABELS:
            break
    return out


async def _project_bucket(db: AsyncSession, project_id: uuid.UUID) -> str:
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(400, "project not found")
    return project.minio_bucket


async def _resolve_folder_by_key(db: AsyncSession, bucket: str, key: str) -> uuid.UUID | None:
    prefix = key.rsplit("/", 1)[0] + "/" if "/" in key else ""
    stmt = select(Folder).where(Folder.minio_prefix == prefix)
    res = await db.execute(stmt)
    folder = res.scalar_one_or_none()
    return folder.id if folder else None
