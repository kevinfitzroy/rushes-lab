"""#153 notifications router 单测 — 不连 DB。

用 FastAPI dependency_overrides 注入 stub db / stub current user,
覆盖 GET 列表(分页 + 未读计数)与 POST mark-read(ids / all / 参数校验)。
真 SQL 行为由容器内 e2e 覆盖(tests/test_notifications_e2e.py)。
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.db.session import get_db
from app.deps import CurrentUser, get_current_user
from app.routers import notifications as mod

ME_ID = uuid.uuid4()


class StubRow:
    """execute 返回的通知行替身。"""

    def __init__(self, nid: uuid.UUID, *, read: bool = False) -> None:
        self.id = nid
        self.kind = "approval_pending"
        self.title = "新的权限申请"
        self.body = "理由:测试"
        self.link = "/ms-static/web/approvals"
        self.read_at = datetime.now(UTC) if read else None
        self.created_at = datetime.now(UTC)


class StubDB:
    def __init__(self, rows: list[StubRow], unread: int) -> None:
        self.rows = rows
        self.unread = unread
        self.commits = 0
        self.marked: list[uuid.UUID] = []

    async def execute(self, stmt: object) -> SimpleNamespace:
        text = str(stmt)
        if "count(" in text and "read_at IS NULL" in text:
            # unread 计数查询(SQLAlchemy Result 直接有 scalar_one)
            return SimpleNamespace(scalar_one=lambda: self.unread)
        if "count(" in text:
            # total 计数查询
            return SimpleNamespace(scalar_one=lambda: len(self.rows))
        if "read_at IS NULL" in text and "id IN" in text:
            # mark-read 的未读 + ids 过滤
            return SimpleNamespace(
                scalars=lambda: SimpleNamespace(
                    all=lambda: [r for r in self.rows if r.read_at is None]))
        if "read_at IS NULL" in text:
            # mark-read all 的未读行
            return SimpleNamespace(
                scalars=lambda: SimpleNamespace(
                    all=lambda: [r for r in self.rows if r.read_at is None]))
        # 列表查询:倒序分页
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: list(self.rows)))

    async def commit(self) -> None:
        self.commits += 1


def make_client(db: StubDB) -> AsyncClient:
    app = FastAPI()
    app.include_router(mod.router, prefix="/api/v1/notifications")

    async def override_db():
        yield db

    async def override_user():
        return CurrentUser(id=ME_ID, name="测试")

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_list_notifications_pagination_and_unread() -> None:
    r1, r2 = StubRow(uuid.uuid4()), StubRow(uuid.uuid4(), read=True)
    db = StubDB([r1, r2], unread=1)
    async with make_client(db) as ac:
        resp = await ac.get("/api/v1/notifications?limit=50&offset=0")

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert body["unread_count"] == 1
    assert len(body["items"]) == 2
    assert body["items"][0]["id"] == str(r1.id)
    assert body["items"][0]["read_at"] is None
    assert body["items"][1]["read_at"] is not None


@pytest.mark.asyncio
async def test_list_notifications_requires_auth() -> None:
    """未认证 → 401(get_current_user 依赖抛 401)。"""
    app = FastAPI()
    app.include_router(mod.router, prefix="/api/v1/notifications")
    # get_current_user 未认证路径会 touch request.app.state.auth(无 cookie 时不调用其方法)
    app.state.auth = SimpleNamespace()  # type: ignore[attr-defined]

    async def override_db():
        yield StubDB([], 0)

    app.dependency_overrides[get_db] = override_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/v1/notifications")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_mark_read_by_ids() -> None:
    r1, r2 = StubRow(uuid.uuid4()), StubRow(uuid.uuid4())
    db = StubDB([r1, r2], unread=2)
    async with make_client(db) as ac:
        resp = await ac.post(
            "/api/v1/notifications/mark-read", json={"ids": [str(r1.id)]},
        )
    assert resp.status_code == 200
    assert resp.json() == {"updated": 2}  # stub 返全部未读行(ids 过滤由真 SQL 负责)
    assert db.commits == 1


@pytest.mark.asyncio
async def test_mark_read_all() -> None:
    db = StubDB([StubRow(uuid.uuid4()), StubRow(uuid.uuid4())], unread=2)
    async with make_client(db) as ac:
        resp = await ac.post("/api/v1/notifications/mark-read", json={"all": True})
    assert resp.status_code == 200
    assert resp.json() == {"updated": 2}


@pytest.mark.asyncio
async def test_mark_read_neither_ids_nor_all_400() -> None:
    async with make_client(StubDB([], 0)) as ac:
        resp = await ac.post("/api/v1/notifications/mark-read", json={})
    assert resp.status_code == 400
    assert "至少" in resp.json()["detail"]
