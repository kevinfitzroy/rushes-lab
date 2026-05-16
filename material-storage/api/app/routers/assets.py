"""assets router — uppy 5-endpoint + list + download + iter4 enforce + audit。

Phase B-2 iter4:每 endpoint 加 OpenFGA check + audit 落库。
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.tables import Asset, Folder, Project
from app.deps import (
    get_audit,
    get_current_user_id,
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
    user_id: uuid.UUID = Depends(get_current_user_id),
    ctx: dict = Depends(get_request_context),
) -> UploadMultipartCreateOut:
    folder = await db.get(Folder, payload.folder_id)
    if not folder:
        raise HTTPException(404, "folder not found")

    # check can_edit folder(普通 folder:project editor 自动;sensitive folder:invited admin only)
    allowed = await permissions.check(
        user_id=str(user_id),
        relation="can_edit",
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
    user_id: uuid.UUID = Depends(get_current_user_id),  # 至少要认证;细粒度上传 check 在 create_upload 已做
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
    db: AsyncSession = Depends(get_db),
    permissions: PermissionsService = Depends(get_permissions),
    presign: PresignService = Depends(get_presign),
    audit: AuditService = Depends(get_audit),
    user_id: uuid.UUID = Depends(get_current_user_id),
    ctx: dict = Depends(get_request_context),
) -> AssetOut:
    folder_id = await _resolve_folder_by_key(db, payload.bucket, payload.key)
    if not folder_id:
        raise HTTPException(400, detail=f"folder for key {payload.key} not found")

    folder = await db.get(Folder, folder_id)
    if not folder:
        raise HTTPException(500, "folder lookup race")

    # 再次 check(防 user create_upload 后被 revoke)
    allowed = await permissions.check(
        user_id=str(user_id),
        relation="can_edit",
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
        parent_folder_id=str(folder.id),
        parent_is_sensitive=folder.is_sensitive,
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

    return AssetOut.model_validate(asset)


@router.delete("/uploads/{upload_id}", status_code=204)
async def abort_upload(
    upload_id: str,
    bucket: str = Query(...),
    key: str = Query(...),
    presign: PresignService = Depends(get_presign),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> None:
    """主动 abort multipart;凡是认证 user 都可 abort 自己 upload。"""
    presign.abort_multipart_upload(bucket, key, upload_id)


# ─── list assets ──────────────────────────────────────────────────────────────
@router.get("", response_model=list[AssetOut])
async def list_assets(
    folder_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    permissions: PermissionsService = Depends(get_permissions),
    user_id: uuid.UUID = Depends(get_current_user_id),
    limit: int = 100,
    offset: int = 0,
) -> list[AssetOut]:
    folder = await db.get(Folder, folder_id)
    if not folder:
        raise HTTPException(404, "folder not found")

    # check can_view folder
    allowed = await permissions.check(
        user_id=str(user_id),
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
    user_id: uuid.UUID = Depends(get_current_user_id),
    ctx: dict = Depends(get_request_context),
) -> DownloadLinkOut:
    """签 presigned GET URL;check can_download asset + audit signed_url_issued。"""
    asset = await db.get(Asset, asset_id)
    if not asset:
        raise HTTPException(404, "asset not found")

    allowed = await permissions.check(
        user_id=str(user_id),
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
