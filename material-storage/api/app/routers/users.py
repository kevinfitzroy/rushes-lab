"""users router — fuzzy search 给前端 UserPicker(a2.5)。

endpoints:
  GET /api/v1/users?q=&limit=  — admin only,fuzzy name/email/open_id 搜
                                 return id/open_id/name/email/avatar

权限:任意 project can_admin 才能调(PoC 简化 — 全公司同 org 即可,
     生产可严:必须有至少一个 project admin tuple)。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.tables import User
from app.deps import CurrentUser, get_current_user

log = logging.getLogger(__name__)
router = APIRouter()


class UserBrief(BaseModel):
    id: str
    open_id: str
    union_id: str | None = None
    name: str
    email: str | None = None


@router.get("", response_model=list[UserBrief])
async def search_users(
    q: str = Query("", description="模糊关键字,匹配 name/email/open_id;留空 = 返前 N"),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> list[UserBrief]:
    """fuzzy 搜 user — UserPicker autocomplete 用。"""
    _ = user.id  # 至少要认证;细粒度 admin 检查 D iter4 后端 enforcement
    stmt = select(User).where(User.is_active.is_(True))
    term = q.strip()
    if term:
        like = f"%{term}%"
        stmt = stmt.where(
            or_(
                User.name.ilike(like),
                User.email.ilike(like),
                User.feishu_open_id.ilike(like),
            )
        )
    stmt = stmt.order_by(User.name).limit(limit)
    res = await db.execute(stmt)
    return [
        UserBrief(
            id=str(u.id),
            open_id=u.feishu_open_id,
            union_id=u.feishu_union_id,
            name=u.name,
            email=u.email,
        )
        for u in res.scalars().all()
    ]
