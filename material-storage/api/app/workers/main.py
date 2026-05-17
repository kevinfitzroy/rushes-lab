"""arq worker entrypoint。

启动:
  arq app.workers.main.WorkerSettings

tasks:
  - generate_thumbnail(asset_id):图片 → Pillow thumbnail 1024 → MinIO thumbnails/
  - transcode_proxy:视频转码(后续 iter)
"""
from __future__ import annotations

import io
import logging
import uuid
from typing import Any

import boto3
from arq.connections import RedisSettings
from botocore.client import Config
from PIL import Image
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.session import get_sessionmaker
from app.db.tables import Asset
from app.settings import get_settings

log = logging.getLogger("worker")

# image content_types we handle
_IMAGE_PREFIXES = ("image/",)
_THUMBNAIL_MAX_PX = 1024
_THUMBNAIL_QUALITY = 80


async def generate_thumbnail(ctx: dict, asset_id: str) -> dict[str, Any]:
    """图片缩略图生成。

    流程:
      1. db 查 asset(content_type / minio_bucket / minio_key)
      2. content_type 不 image/* → skip
      3. boto3 download_fileobj 原图
      4. Pillow open + thumbnail(1024)+ JPEG quality=80
      5. 上传 thumbnails/{asset_id}.jpg
      6. db assets.tags['thumbnail_key'] 写入
      7. 失败 → tags['thumbnail_failed'] = reason(便于排查)
    """
    settings = get_settings()
    sm = get_sessionmaker()
    aid = uuid.UUID(asset_id)

    async with sm() as db:
        asset = await db.get(Asset, aid)
        if asset is None:
            return {"status": "asset_not_found", "asset_id": asset_id}
        if asset.deleted_at is not None:
            return {"status": "asset_deleted", "asset_id": asset_id}
        if not asset.content_type or not asset.content_type.startswith(_IMAGE_PREFIXES):
            return {"status": "skip_non_image", "content_type": asset.content_type}

        bucket = asset.minio_bucket
        src_key = asset.minio_key

    # MinIO client(internal endpoint — worker 在 docker 内)
    s3 = boto3.client(
        "s3",
        endpoint_url=settings.minio_endpoint_internal,
        aws_access_key_id=settings.minio_access_key,
        aws_secret_access_key=settings.minio_secret_key,
        config=Config(signature_version="s3v4", region_name="us-east-1"),
    )

    try:
        # 1) 拉原图(内存)
        buf = io.BytesIO()
        s3.download_fileobj(bucket, src_key, buf)
        buf.seek(0)

        # 2) Pillow 处理
        img = Image.open(buf)
        # 兼容 EXIF orientation(手机拍照常用)
        try:
            from PIL import ImageOps
            img = ImageOps.exif_transpose(img)
        except Exception:  # noqa: BLE001
            pass
        # RGBA / P / L → 转 RGB(JPEG 需要)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        img.thumbnail((_THUMBNAIL_MAX_PX, _THUMBNAIL_MAX_PX), Image.Resampling.LANCZOS)

        # 3) 编码 JPEG
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=_THUMBNAIL_QUALITY, optimize=True)
        out.seek(0)
        thumbnail_size = out.getbuffer().nbytes

        # 4) 上传
        thumbnail_key = f"thumbnails/{asset_id}.jpg"
        s3.put_object(
            Bucket=bucket, Key=thumbnail_key, Body=out,
            ContentType="image/jpeg",
            Metadata={"source_asset": asset_id, "max_px": str(_THUMBNAIL_MAX_PX)},
        )
        log.info("thumbnail generated asset=%s key=%s size=%d w=%d h=%d",
                 asset_id, thumbnail_key, thumbnail_size, img.width, img.height)
    except Exception as e:
        log.exception("thumbnail fail asset=%s err=%s", asset_id, e)
        async with sm() as db:
            a = await db.get(Asset, aid)
            if a:
                tags = dict(a.tags or {})
                tags["thumbnail_failed"] = str(e)[:200]
                a.tags = tags
                await db.commit()
        return {"status": "failed", "asset_id": asset_id, "error": str(e)[:200]}

    # 5) 更新 db
    async with sm() as db:
        a = await db.get(Asset, aid)
        if a:
            tags = dict(a.tags or {})
            tags["thumbnail_key"] = thumbnail_key
            tags["thumbnail_size_bytes"] = thumbnail_size
            tags["thumbnail_width"] = img.width
            tags["thumbnail_height"] = img.height
            tags.pop("thumbnail_failed", None)
            a.tags = tags
            await db.commit()

    return {
        "status": "ok", "asset_id": asset_id,
        "thumbnail_key": thumbnail_key, "size_bytes": thumbnail_size,
    }


async def transcode_proxy(ctx: dict, asset_id: str) -> dict[str, Any]:
    """ffmpeg → 720p H.264(视频缩略图 / 转码 — 后续 iter)。"""
    return {"asset_id": asset_id, "status": "stub_iter_next"}


# ─── arq settings ────────────────────────────────────────────────────────────
def _build_redis_settings() -> RedisSettings:
    """从 settings.redis_url 解析(优先 env REDIS_URL)。"""
    from urllib.parse import urlparse
    settings = get_settings()
    url = urlparse(str(settings.redis_url))
    return RedisSettings(
        host=url.hostname or "localhost",
        port=url.port or 6379,
        database=int(url.path.lstrip("/") or 0),
        password=url.password,
    )


class WorkerSettings:
    functions = [generate_thumbnail, transcode_proxy]
    redis_settings = _build_redis_settings()
    max_jobs = 4
    job_timeout = 60   # 单 task 最长 60s,超时 kill
    keep_result = 300  # 结果保留 5 min(arq 默认 0)
