"""groups router — 本地用户组查询(给前端 GroupPicker / SubjectPicker;#150 本地化)。

#150 起数据源从飞书通讯录(contact/group/simplelist)改为本地 groups 表,
成员数来自 group_memberships join。管理端 CRUD 见 routers/directory.py。

需 admin。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.tables import Group, GroupMembership
from app.deps import CurrentUser, require_admin

log = logging.getLogger(__name__)
router = APIRouter()


class GroupBrief(BaseModel):
    id: str
    name: str
    description: str | None = None
    member_count: int | None = None


@router.get("", response_model=list[GroupBrief])
async def search_groups(
    q: str = Query("", description="name 模糊关键字(留空 = 返前 N)"),
    limit: int = Query(30, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_admin),
) -> list[GroupBrief]:
    """本地组列表 → name 模糊 filter。无组 → 空数组(不是 404)。"""
    _ = user.id
    term = q.strip()
    count = func.count(GroupMembership.user_id)
    stmt = (
        select(Group, count)
        .outerjoin(GroupMembership, GroupMembership.group_id == Group.id)
        .group_by(Group.id)
        .order_by(Group.name)
        .limit(limit)
    )
    if term:
        like = f"%{term}%"
        stmt = (
            select(Group, count)
            .outerjoin(GroupMembership, GroupMembership.group_id == Group.id)
            .where(func.lower(Group.name).like(func.lower(like)))
            .group_by(Group.id)
            .order_by(Group.name)
            .limit(limit)
        )
    res = await db.execute(stmt)
    return [
        GroupBrief(
            id=str(g.id),
            name=g.name,
            description=g.description,
            member_count=cnt,
        )
        for g, cnt in res.all()
    ]
