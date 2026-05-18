"""Maintenance banner — deploy 期间给前端推一个 modal,避免测试人员中途惊吓。

读写约定
========
- redis key `maintenance:banner` 存 JSON {active, message, issues, started_at, ends_at}
- 写由 deploy_server2.sh 通过 ssh + docker exec ms-redis redis-cli SETEX 写入,
  TTL=900s 作 catastrophic fallback(脚本崩了 15 分钟后 banner 自然消失)
- deploy 完成后脚本 DEL 立即撤
- 本 GET endpoint **公开**(banner 就是给未登录用户也看的),无 auth
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

from fastapi import APIRouter, Request
from pydantic import BaseModel

log = logging.getLogger(__name__)
router = APIRouter()


class IssueBrief(BaseModel):
    number: int
    summary: str


class MaintenanceBanner(BaseModel):
    active: bool
    message: str | None = None
    issues: list[IssueBrief] = []
    started_at: datetime | None = None
    ends_at: datetime | None = None


@router.get("/banner", response_model=MaintenanceBanner)
async def get_banner(request: Request) -> MaintenanceBanner:
    redis = request.app.state.redis
    raw = await redis.get("maintenance:banner")
    if not raw:
        return MaintenanceBanner(active=False)
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as e:
        log.warning("maintenance:banner JSON parse error: %s raw=%r", e, raw)
        return MaintenanceBanner(active=False)
    return MaintenanceBanner(**payload)
