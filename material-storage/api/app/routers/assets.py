"""assets router — uppy 5-endpoint multipart + list + download link。

Phase B-2 first batch:基础流程,未含 OpenFGA enforce / audit 落库 / 敏感代理 stream。
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.tables import Asset, Folder, Project
from app.models import (
    AssetOut,
    DownloadLinkOut,
    UploadCompleteIn,
    UploadMultipartCreateOut,
    UploadPartUrlOut,
    UploadUrlRequest,
)
from app.settings import get_settings

router = APIRouter()


@router.post("/uploads", response_model=UploadMultipartCreateOut)
async def create_upload(
    payload: UploadUrlRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> UploadMultipartCreateOut:
    folder = await db.get(Folder, payload.folder_id)
    if not folder:
        raise HTTPException(404, "folder not found")

    key = f"{folder.minio_prefix.rstrip('/')}/{payload.filename}"
    bucket = await _project_bucket(db, folder.project_id)

    presign = request.app.state.presign
    upload_id = presign.create_multipart_upload(bucket, key, payload.content_type)
    return UploadMultipartCreateOut(upload_id=upload_id, key=key, bucket=bucket)


@router.get("/uploads/{upload_id}/parts/{part_number}", response_model=UploadPartUrlOut)
async def sign_part(
    request: Request,
    upload_id: str,
    part_number: int,
    bucket: str = Query(...),
    key: str = Query(...),
) -> UploadPartUrlOut:
    settings = get_settings()
    presign = request.app.state.presign
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
) -> AssetOut:
    presign = request.app.state.presign
    result = presign.complete_multipart_upload(
        payload.bucket, payload.key, upload_id, payload.parts  # type: ignore[arg-type]
    )

    folder_id = await _resolve_folder_by_key(db, payload.bucket, payload.key)
    if not folder_id:
        raise HTTPException(400, detail=f"folder for key {payload.key} not found")

    asset = Asset(
        id=uuid.uuid4(),
        folder_id=folder_id,
        filename=payload.key.rsplit("/", 1)[-1],
        minio_bucket=payload.bucket,
        minio_key=payload.key,
        etag=result.get("etag"),
        minio_version_id=result.get("version_id"),
        size_bytes=0,  # complete 不返 size;Phase B-2 后续 head_object enrich
        content_type=None,
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)

    folder = await db.get(Folder, folder_id)
    if folder:
        permissions = request.app.state.permissions
        # v3 重新引入 sensitive_folder type(邀请制可见性)— parent_is_sensitive 必传
        await permissions.bootstrap_asset(
            asset_id=str(asset.id),
            parent_folder_id=str(folder.id),
            parent_is_sensitive=folder.is_sensitive,
        )

    return AssetOut.model_validate(asset)


@router.delete("/uploads/{upload_id}", status_code=204)
async def abort_upload(
    request: Request,
    upload_id: str,
    bucket: str = Query(...),
    key: str = Query(...),
) -> None:
    presign = request.app.state.presign
    presign.abort_multipart_upload(bucket, key, upload_id)


@router.get("", response_model=list[AssetOut])
async def list_assets(
    folder_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    limit: int = 100,
    offset: int = 0,
) -> list[AssetOut]:
    stmt = (
        select(Asset)
        .where(Asset.folder_id == folder_id, Asset.deleted_at.is_(None))
        .order_by(Asset.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    res = await db.execute(stmt)
    return [AssetOut.model_validate(r) for r in res.scalars().all()]


@router.post("/{asset_id}/download-link", response_model=DownloadLinkOut)
async def get_download_link(
    asset_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> DownloadLinkOut:
    """签 presigned GET URL。

    model 简化 v2 后:不再二分 sensitive/普通 folder;所有 asset 同一签 URL TTL。
    权限粒度统一通过 OpenFGA(`can_download` = `member or explicit_downloader`)。
    Phase B-2 next iter 会加 OpenFGA `check` enforce。
    """
    asset = await db.get(Asset, asset_id)
    if not asset:
        raise HTTPException(404, "asset not found")

    settings = get_settings()
    presign = request.app.state.presign
    ttl = settings.presigned_normal_ttl_seconds
    url = presign.sign_get_url(asset.minio_bucket, asset.minio_key, ttl)
    # is_sensitive 字段保留(business labeling),但不影响行为
    return DownloadLinkOut(url=url, expires_in=ttl, is_sensitive=False)


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
