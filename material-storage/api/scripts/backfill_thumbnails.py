"""一次性 backfill 老 assets 缩略图(B-4;ADR-0008 P1 后支持 --force 重生成)。

执行:
  docker exec ms-api python -m scripts.backfill_thumbnails              # 只补缺缩略图的
  docker exec ms-api python -m scripts.backfill_thumbnails --force     # 全部重生成(切 ms-thumbs 用)

行为:
  - 默认:扫 content_type=image/* 或 video/* 且 tags 无 thumbnail_key 的 asset → enqueue
    (image → generate_thumbnail;video → generate_video_thumbnail)
  - --force:忽略已有 thumbnail_key,全部重新 enqueue —— 切独立缩略图 bucket
    (MINIO_THUMBNAIL_BUCKET=ms-thumbs)后,存量图默认 skip(普通 backfill 是 no-op),
    必须 --force 重生成到新 bucket
  - 失败 / 缺 worker 时 log + 不阻塞。
"""
from __future__ import annotations

import asyncio
import logging
import sys

from sqlalchemy import or_, select

from app.db.session import get_sessionmaker
from app.db.tables import Asset
from app.services.arq_pool import create_arq_pool
from app.settings import get_settings

logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
log = logging.getLogger("backfill")

FORCE = "--force" in sys.argv[1:]


async def main() -> None:
    settings = get_settings()
    sm = get_sessionmaker()
    pool = await create_arq_pool(settings)

    async with sm() as db:
        stmt = (
            select(Asset)
            .where(
                or_(
                    Asset.content_type.like("image/%"),
                    Asset.content_type.like("video/%"),
                ),
                Asset.deleted_at.is_(None),
            )
        )
        res = await db.execute(stmt)
        assets = list(res.scalars())

    skipped = enqueued = 0
    for a in assets:
        tags = a.tags or {}
        if not FORCE and tags.get("thumbnail_key"):
            skipped += 1
            continue
        job = (
            "generate_video_thumbnail"
            if (a.content_type or "").startswith("video/")
            else "generate_thumbnail"
        )
        await pool.enqueue_job(job, str(a.id))
        enqueued += 1
        if enqueued % 50 == 0:
            log.info("enqueued %d so far…", enqueued)

    await pool.aclose()
    log.info(
        "DONE — %d assets total%s, %d already had thumbnail (skipped), %d enqueued",
        len(assets), " (--force 全量重生成)" if FORCE else "",
        skipped, enqueued,
    )


if __name__ == "__main__":
    asyncio.run(main())
