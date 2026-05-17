"""arq Redis pool for ms-api → enqueue worker tasks。

由 main.py lifespan create + 挂 app.state.arq_pool。enqueue helper:
    await arq_pool.enqueue_job('generate_thumbnail', asset_id)
"""
from __future__ import annotations

import logging
from urllib.parse import urlparse

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.settings import Settings

log = logging.getLogger(__name__)


async def create_arq_pool(settings: Settings) -> ArqRedis:
    url = urlparse(str(settings.redis_url))
    pool = await create_pool(RedisSettings(
        host=url.hostname or "localhost",
        port=url.port or 6379,
        database=int(url.path.lstrip("/") or 0),
        password=url.password,
    ))
    log.info("arq pool ready redis=%s:%s", url.hostname, url.port)
    return pool


async def enqueue_thumbnail(pool: ArqRedis, asset_id: str) -> None:
    """fire-and-forget;失败仅 log,不阻塞业务。"""
    try:
        await pool.enqueue_job("generate_thumbnail", asset_id)
    except Exception as e:  # noqa: BLE001
        log.warning("enqueue_thumbnail fail asset=%s err=%s", asset_id, e)
