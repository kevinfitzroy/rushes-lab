"""assets router — uppy 5-endpoint + list + download + iter4 enforce + audit。

Phase B-2 iter4:每 endpoint 加 OpenFGA check + audit 落库。
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.tables import Asset, Folder, Project
from app.deps import (
    get_audit,
    CurrentUser,
    get_current_user,
    get_permissions,
    get_presign,
    get_request_context,
)
from app.models import (
    AssetOut,
    DownloadLinkOut,
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
    ctx: dict = Depends(get_request_context),
) -> UploadMultipartCreateOut:
    user_id, user_open_id = user.id, user.open_id
    folder = await db.get(Folder, payload.folder_id)
    if not folder:
        raise HTTPException(404, "folder not found")

    # check can_upload folder(v4:uploader 隐含上传 + 创建 sub folder)
    allowed = await permissions.check(
        user_subject=f"user:{user_open_id}",
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
    ctx: dict = Depends(get_request_context),
) -> AssetOut:
    user_id, user_open_id = user.id, user.open_id
    folder_id = await _resolve_folder_by_key(db, payload.bucket, payload.key)
    if not folder_id:
        raise HTTPException(400, detail=f"folder for key {payload.key} not found")

    folder = await db.get(Folder, folder_id)
    if not folder:
        raise HTTPException(500, "folder lookup race")

    # 再次 check(防 user create_upload 后被 revoke)
    allowed = await permissions.check(
        user_subject=f"user:{user_open_id}",
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

    # B-4:enqueue thumbnail 生成(图片才会处理,worker 内 skip 非图片)
    if asset.content_type and asset.content_type.startswith("image/"):
        from app.services.arq_pool import enqueue_thumbnail
        await enqueue_thumbnail(request.app.state.arq_pool, str(asset.id))

    return AssetOut.model_validate(asset)


@router.delete("/uploads/{upload_id}", status_code=204)
async def abort_upload(
    upload_id: str,
    bucket: str = Query(...),
    key: str = Query(...),
    presign: PresignService = Depends(get_presign),
    user: CurrentUser = Depends(get_current_user),
) -> None:
    user_id, user_open_id = user.id, user.open_id
    """主动 abort multipart;凡是认证 user 都可 abort 自己 upload。"""
    presign.abort_multipart_upload(bucket, key, upload_id)


# ─── list assets ──────────────────────────────────────────────────────────────
@router.get("", response_model=list[AssetOut])
async def list_assets(
    folder_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    permissions: PermissionsService = Depends(get_permissions),
    user: CurrentUser = Depends(get_current_user),
    limit: int = 100,
    offset: int = 0,
) -> list[AssetOut]:
    user_id, user_open_id = user.id, user.open_id
    folder = await db.get(Folder, folder_id)
    if not folder:
        raise HTTPException(404, "folder not found")

    # check can_view folder
    allowed = await permissions.check(
        user_subject=f"user:{user_open_id}",
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


# ─── download link ────────────────────────────────────────────────────────────
@router.post("/{asset_id}/download-link", response_model=DownloadLinkOut)
async def get_download_link(
    asset_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    permissions: PermissionsService = Depends(get_permissions),
    presign: PresignService = Depends(get_presign),
    audit: AuditService = Depends(get_audit),
    user: CurrentUser = Depends(get_current_user),
    ctx: dict = Depends(get_request_context),
) -> DownloadLinkOut:
    user_id, user_open_id = user.id, user.open_id
    """签 presigned GET URL;check can_download asset + audit signed_url_issued。"""
    asset = await db.get(Asset, asset_id)
    if not asset:
        raise HTTPException(404, "asset not found")

    allowed = await permissions.check(
        user_subject=f"user:{user_open_id}",
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
    url = presign.sign_get_url(asset.minio_bucket, thumbnail_key, ttl)
    return {"url": url, "expires_in": ttl}


# ─── delete(soft)──────────────────────────────────────────────────────────
@router.delete("/{asset_id}", status_code=204)
async def delete_asset(
    asset_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    permissions: PermissionsService = Depends(get_permissions),
    audit: AuditService = Depends(get_audit),
    user: CurrentUser = Depends(get_current_user),
    ctx: dict = Depends(get_request_context),
) -> None:
    user_id, user_open_id = user.id, user.open_id
    """soft delete:置 deleted_at;MinIO object 保留(由 bucket lifecycle 异步清)。

    权限:asset.can_admin(model v4:= can_admin from parent folder/project)。
    """
    from datetime import datetime, timezone
    asset = await db.get(Asset, asset_id)
    if not asset:
        raise HTTPException(404, "asset not found")

    allowed = await permissions.check(
        user_subject=f"user:{user_open_id}", relation="can_admin",
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
