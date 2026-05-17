"""一次性 backfill 老 assets 缩略图(B-4)。

执行:
  docker exec ms-api python -m scripts.backfill_thumbnails

行为:
  扫所有 content_type=image/* 且 tags 无 thumbnail_key 的 asset → enqueue;
  失败 / 缺 worker 时 log + 不阻塞。
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from app.db.session import get_sessionmaker
from app.db.tables import Asset
from app.services.arq_pool import create_arq_pool
from app.settings import get_settings

logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
log = logging.getLogger("backfill")


async def main() -> None:
    settings = get_settings()
    sm = get_sessionmaker()
    pool = await create_arq_pool(settings)

    async with sm() as db:
        stmt = (
            select(Asset)
            .where(
                Asset.content_type.like("image/%"),
                Asset.deleted_at.is_(None),
            )
        )
        res = await db.execute(stmt)
        assets = list(res.scalars())

    skipped = enqueued = 0
    for a in assets:
        tags = a.tags or {}
        if tags.get("thumbnail_key"):
            skipped += 1
            continue
        await pool.enqueue_job("generate_thumbnail", str(a.id))
        enqueued += 1
        if enqueued % 50 == 0:
            log.info("enqueued %d so far…", enqueued)

    await pool.aclose()
    log.info("DONE — %d image assets total, %d already had thumbnail (skipped), %d enqueued",
             len(assets), skipped, enqueued)


if __name__ == "__main__":
    asyncio.run(main())
