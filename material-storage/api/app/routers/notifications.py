"""notifications router — 应用内通知中心(#153)。

endpoints:
  GET  /api/v1/notifications           — 当前用户通知列表(分页 + total + unread_count)
  POST /api/v1/notifications/mark-read — 标记已读(ids 单条/多条,或 all 全部)

设计:
- 轮询即可(局域网规模,不做 WebSocket);前端 badge 用 refetchInterval 轮询
- 只读当前用户自己的通知(user_id 隔离);不做跨用户可见性
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.tables import Notification
from app.deps import CurrentUser, get_current_user

router = APIRouter()


# ─── output / input models ────────────────────────────────────────────────────
class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    title: str
    body: str | None
    link: str | None
    read_at: datetime | None
    created_at: datetime


class NotificationsListOut(BaseModel):
    items: list[NotificationOut]
    total: int
    unread_count: int


class MarkReadIn(BaseModel):
    # 二选一:给 ids 标记指定条;或 all=true 标记全部(两者都空 = 400)
    ids: list[uuid.UUID] | None = Field(None, max_length=200)
    all: bool = False


class MarkReadOut(BaseModel):
    updated: int


# ─── endpoints ────────────────────────────────────────────────────────────────
@router.get("", response_model=NotificationsListOut)
async def list_notifications(
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> NotificationsListOut:
    """当前用户的通知,按 created_at 倒序;附 total + unread_count(badge 轮询用)。"""
    base = select(Notification).where(Notification.user_id == user.id)
    total = (await db.execute(
        select(func.count()).select_from(Notification)
        .where(Notification.user_id == user.id),
    )).scalar_one()
    unread = (await db.execute(
        select(func.count()).select_from(Notification)
        .where(Notification.user_id == user.id, Notification.read_at.is_(None)),
    )).scalar_one()

    res = await db.execute(
        base.order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(limit).offset(offset),
    )
    return NotificationsListOut(
        items=[NotificationOut.model_validate(r) for r in res.scalars().all()],
        total=total,
        unread_count=unread,
    )


@router.post("/mark-read", response_model=MarkReadOut)
async def mark_read(
    payload: MarkReadIn,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> MarkReadOut:
    """标记已读:payload.ids(限本人)或 payload.all(全部未读)。"""
    if not payload.all and not payload.ids:
        raise HTTPException(400, "ids 与 all 至少提供一个")

    stmt = select(Notification).where(
        Notification.user_id == user.id, Notification.read_at.is_(None),
    )
    if not payload.all and payload.ids:
        stmt = stmt.where(Notification.id.in_(payload.ids))
    res = await db.execute(stmt)
    rows = list(res.scalars().all())

    now = datetime.now(UTC)
    for r in rows:
        r.read_at = now
    await db.commit()
    return MarkReadOut(updated=len(rows))
