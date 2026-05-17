"""groups router — 飞书"用户组"实时查询(给前端 GroupPicker)。

转调飞书 OpenAPI `/contact/v3/group/simplelist`(已封装在 FeishuContactClient),
本地 name 模糊 filter;不入 db,无缓存(PoC 量级 < 100 组,可接受;高频可加 Redis cache)。

需 admin。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from app.deps import CurrentUser, require_admin
from app.services.feishu_client import FeishuAPIError
from app.services.feishu_contact import FeishuContactClient

log = logging.getLogger(__name__)
router = APIRouter()


class GroupBrief(BaseModel):
    id: str
    name: str
    description: str | None = None
    member_count: int | None = None


@router.get("", response_model=list[GroupBrief])
async def search_groups(
    request: Request,
    q: str = Query("", description="name 模糊关键字(留空 = 返前 N)"),
    limit: int = Query(30, ge=1, le=200),
    user: CurrentUser = Depends(require_admin),
) -> list[GroupBrief]:
    """实时查飞书用户组列表 → 本地 filter。

    无组 → 返空数组(不是 404)。
    权限不足(飞书 contact:group:readonly 未开)→ 也返空 + log warning。
    """
    _ = user.id
    feishu = request.app.state.feishu_client
    contact = FeishuContactClient(feishu)
    term = q.strip().lower()

    items: list[GroupBrief] = []
    try:
        async for g in contact.list_groups():
            name = g.get("name") or ""
            if term and term not in name.lower():
                continue
            items.append(GroupBrief(
                id=g.get("id", ""),
                name=name,
                description=g.get("description") or None,
                member_count=g.get("member_user_count"),
            ))
            if len(items) >= limit:
                break
    except FeishuAPIError as e:
        log.warning("search_groups feishu fail code=%s msg=%s", e.code, e.msg)
        return []
    except Exception as e:  # noqa: BLE001
        log.warning("search_groups unexpected fail: %s", e)
        return []
    return items
