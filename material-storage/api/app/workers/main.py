"""arq worker entrypoint。

启动:
  arq app.workers.main.WorkerSettings

tasks:
  - generate_thumbnail(asset_id):图片 → Pillow thumbnail 1024 → MinIO thumbnails/
  - generate_video_thumbnail(asset_id):视频 → ffmpeg 抽帧 → MinIO thumbnails/(B-4 iter2, #101)
  - mark_expired_approvals:cron 扫已过期 approval,改 status
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


_VIDEO_PREFIXES = ("video/",)
_VIDEO_THUMBNAIL_MAX_BYTES = 50 * 1024 * 1024   # 50MB cap pilot(ROADMAP §63 风险段)
_VIDEO_HEAD_RANGE = 10 * 1024 * 1024            # 只拉头部 10MB 给 ffmpeg 用,避免大文件拉全
_FFMPEG_TIMEOUT_SEC = 30                         # subprocess 硬上限


def _extract_video_frame(in_path: Any, out_path: Any, timeout: int) -> bool:
    """ffmpeg 抽 1 帧:先试 1s(避首帧黑屏)再兜底 0s。出非空 jpg 返 True,否则 False。

    subprocess.TimeoutExpired 不在此吞掉,交给调用方统一处理(走 ffmpeg_timeout 兜底)。
    head + fallback 两条路径都调本 helper,保证 fallback 也享受 1s/0s 双重试(#135)。
    """
    import subprocess
    for ss in ("1", "0"):
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-ss", ss, "-i", str(in_path),
            "-frames:v", "1", "-vf", "scale=1024:-2",
            "-q:v", "3", "-y", str(out_path),
        ]
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
        if proc.returncode == 0 and out_path.exists() and out_path.stat().st_size > 0:
            return True
    return False


async def generate_video_thumbnail(ctx: dict, asset_id: str) -> dict[str, Any]:
    """视频缩略图生成(B-4 iter2, issue #101)。

    流程:
      1. db 查 asset(content_type / size / minio_bucket / minio_key)
      2. content_type 不 video/* → skip
      3. size > 50MB → skip(pilot;后续 deferred queue)
      4. boto3 get_object Range bytes=0-{HEAD_RANGE} 流式拉头部 → /tmp/<aid>.bin
      5. ffmpeg -ss 1 -i in -frames:v 1 -vf scale=1024:-1 out.jpg
         (-ss 1 抽 1s 帧,避开首帧黑屏;若 duration<1s 兜底 -ss 0)
      6. 上传 thumbnails/{asset_id}.jpg + 写 asset.tags.thumbnail_key
      7. 失败兜底 tags['thumbnail_failed']
      finally: cleanup /tmp
    """
    import pathlib
    import subprocess
    import tempfile
    settings = get_settings()
    sm = get_sessionmaker()
    aid = uuid.UUID(asset_id)

    async with sm() as db:
        asset = await db.get(Asset, aid)
        if asset is None:
            return {"status": "asset_not_found", "asset_id": asset_id}
        if asset.deleted_at is not None:
            return {"status": "asset_deleted", "asset_id": asset_id}
        if not asset.content_type or not asset.content_type.startswith(_VIDEO_PREFIXES):
            return {"status": "skip_non_video", "content_type": asset.content_type}
        if asset.size_bytes and asset.size_bytes > _VIDEO_THUMBNAIL_MAX_BYTES:
            return {
                "status": "skip_too_large",
                "size_bytes": asset.size_bytes,
                "cap": _VIDEO_THUMBNAIL_MAX_BYTES,
            }
        bucket = asset.minio_bucket
        src_key = asset.minio_key
        asset_size = asset.size_bytes  # #135: 判定是否需 fallback 拉完整文件(moov-at-end)

    s3 = boto3.client(
        "s3",
        endpoint_url=settings.minio_endpoint_internal,
        aws_access_key_id=settings.minio_access_key,
        aws_secret_access_key=settings.minio_secret_key,
        config=Config(signature_version="s3v4", region_name="us-east-1"),
    )

    tmpdir = pathlib.Path(tempfile.mkdtemp(prefix=f"vthumb-{asset_id}-"))
    in_path = tmpdir / "in.bin"
    out_path = tmpdir / "out.jpg"
    thumbnail_size = 0
    try:
        # 1) 先拉头部 ~10MB(关键帧通常在前几秒;faststart 文件 moov 也在头部)
        resp = s3.get_object(Bucket=bucket, Key=src_key,
                             Range=f"bytes=0-{_VIDEO_HEAD_RANGE - 1}")
        with open(in_path, "wb") as f:
            for chunk in resp["Body"].iter_chunks(chunk_size=1024 * 1024):
                f.write(chunk)

        # 2) ffmpeg 抽帧
        ok = _extract_video_frame(in_path, out_path, _FFMPEG_TIMEOUT_SEC)

        # 2b) #135 fallback:头部抽帧失败 + 文件可能比头部大 → 拉完整文件重试。
        #     moov box 在文件尾部(iOS / 屏录 / ffmpeg 默认输出)时,头部 10MB 不含 moov
        #     → demux fail。size_bytes None 视为"可能很大"一并 fallback。已被上面 50MB cap 兜住,
        #     fallback 最多拉 50MB。faststart 文件头部就成功,不进此路径,无性能回归。
        if not ok and (asset_size is None or asset_size > _VIDEO_HEAD_RANGE):
            log.info("video thumbnail head-fail, fallback to full file asset=%s size=%s",
                     asset_id, asset_size)
            s3.download_file(bucket, src_key, str(in_path))
            ok = _extract_video_frame(in_path, out_path, _FFMPEG_TIMEOUT_SEC)

        if not ok:
            raise RuntimeError("ffmpeg failed to extract frame (head + full fallback)")

        thumbnail_size = out_path.stat().st_size

        # 3) 上传
        thumbnail_key = f"thumbnails/{asset_id}.jpg"
        with open(out_path, "rb") as f:
            s3.put_object(
                Bucket=bucket, Key=thumbnail_key, Body=f,
                ContentType="image/jpeg",
                Metadata={"source_asset": asset_id, "kind": "video_frame"},
            )
        log.info("video thumbnail asset=%s key=%s size=%d", asset_id, thumbnail_key, thumbnail_size)
    except subprocess.TimeoutExpired:
        log.warning("ffmpeg timeout asset=%s", asset_id)
        async with sm() as db:
            a = await db.get(Asset, aid)
            if a:
                tags = dict(a.tags or {})
                tags["thumbnail_failed"] = "ffmpeg_timeout"
                a.tags = tags
                await db.commit()
        return {"status": "failed", "asset_id": asset_id, "error": "ffmpeg_timeout"}
    except Exception as e:
        log.warning("video thumbnail fail asset=%s err=%s", asset_id, e)
        async with sm() as db:
            a = await db.get(Asset, aid)
            if a:
                tags = dict(a.tags or {})
                tags["thumbnail_failed"] = str(e)[:200]
                a.tags = tags
                await db.commit()
        return {"status": "failed", "asset_id": asset_id, "error": str(e)[:200]}
    finally:
        # cleanup /tmp(无论成功失败)
        try:
            if in_path.exists():
                in_path.unlink()
            if out_path.exists():
                out_path.unlink()
            tmpdir.rmdir()
        except Exception:  # noqa: BLE001
            pass

    # 4) 更新 db
    async with sm() as db:
        a = await db.get(Asset, aid)
        if a:
            tags = dict(a.tags or {})
            tags["thumbnail_key"] = thumbnail_key
            tags["thumbnail_size_bytes"] = thumbnail_size
            tags["thumbnail_kind"] = "video_frame"
            tags.pop("thumbnail_failed", None)
            a.tags = tags
            await db.commit()

    return {
        "status": "ok", "asset_id": asset_id,
        "thumbnail_key": thumbnail_key, "size_bytes": thumbnail_size,
    }


async def mark_expired_approvals(ctx: dict) -> dict[str, Any]:
    """polish 3:扫 status='approved' 且 decided_at + duration < now 的 approval → expired。

    注:OpenFGA grant 本身因 non_expired_grant condition 已自动失效,
    这里只更新 status 字段让 UI 显示一致。
    """
    from datetime import datetime, timezone, timedelta
    from sqlalchemy import select, update
    from app.db.tables import ApprovalRequest

    sm = get_sessionmaker()
    now = datetime.now(timezone.utc)
    async with sm() as db:
        # 找候选(避免 SQL 表达式跨 dialect 复杂度,Python 侧 filter)
        stmt = select(ApprovalRequest).where(
            ApprovalRequest.status == "approved",
            ApprovalRequest.duration_seconds.is_not(None),
            ApprovalRequest.decided_at.is_not(None),
        )
        res = await db.execute(stmt)
        candidates = list(res.scalars())
        expired_ids = []
        for a in candidates:
            if a.decided_at is None or a.duration_seconds is None:
                continue
            expires_at = a.decided_at + timedelta(seconds=a.duration_seconds)
            if expires_at < now:
                expired_ids.append(a.id)
        if expired_ids:
            await db.execute(
                update(ApprovalRequest)
                .where(ApprovalRequest.id.in_(expired_ids))
                .values(status="expired")
            )
            await db.commit()
    log.info("mark_expired_approvals: scanned=%d expired=%d",
             len(candidates), len(expired_ids))
    return {"scanned": len(candidates), "expired": len(expired_ids)}


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


# cron schedule: 每 5min(/5 0..55)跑一次 mark_expired_approvals
from arq.cron import cron   # noqa: E402

_CRON_JOBS = [
    cron(mark_expired_approvals, minute=set(range(0, 60, 5))),
]


class WorkerSettings:
    functions = [generate_thumbnail, generate_video_thumbnail, mark_expired_approvals]
    cron_jobs = _CRON_JOBS
    redis_settings = _build_redis_settings()
    max_jobs = 4
    job_timeout = 60
    keep_result = 300
