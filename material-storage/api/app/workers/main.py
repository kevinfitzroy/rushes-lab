"""arq worker entrypoint。

启动:
  arq app.workers.main.WorkerSettings
"""
from arq.connections import RedisSettings


async def transcode_proxy(ctx: dict, asset_id: str) -> dict:
    """ffmpeg → 720p H.264 → dataset B(stub,Phase B-4 实施)。"""
    return {"asset_id": asset_id, "status": "stub"}


async def generate_thumbnail(ctx: dict, asset_id: str) -> dict:
    """Pillow / opencv keyframe(stub)。"""
    return {"asset_id": asset_id, "status": "stub"}


class WorkerSettings:
    functions = [transcode_proxy, generate_thumbnail]
    redis_settings = RedisSettings()  # 从 env REDIS_URL
