"""OIDC service 单元测试 — 无基础设施(scripted fake session,不连 DB)。

覆盖 upsert_user_from_userinfo 的三条分支(F16 review 发现:sub miss 后
按 email 兜底关联已有本地账号,防 IdP 首登重复建号):
  1. oidc_sub 直接命中
  2. sub miss → email 兜底关联已有本地账号(未绑定其它 oidc_sub)
  3. sub miss + email miss → 新建用户
  4. email 命中但已被其它 oidc_sub 占用 → 不抢账号,按新用户建号

网络流(exchange_code / fetch_userinfo)需在容器集成测试里对 mock IdP 验证,
这里只测 upsert 的账号关联逻辑。
"""
from __future__ import annotations

import uuid
from typing import Any

from app.db.tables import User
from app.services.auth import OIDCService
from app.settings import Settings

SUB = "oidc-sub-123"
NAME = "陈小明"
EMAIL = "chen.xiaoming@example.com"
LOCAL_EMAIL = "chen.xiaoming@example.com"


# ─── helpers ─────────────────────────────────────────────────────────────────
def make_settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = dict(
        db_url="postgresql+asyncpg://u:p@localhost:5432/x",
        redis_url="redis://localhost:6379/0",
        minio_endpoint_internal="http://minio:9000",
        minio_endpoint_public="http://localhost:9000",
        minio_access_key="ak",
        minio_secret_key="sk",
        openfga_api_url="http://localhost:8080",
        openfga_store_id="store",
        web_app_base_url="http://localhost/ms-static/web/",
        session_jwt_secret="x" * 32,
        oidc_provider={
            "authorize_endpoint": "https://idp.example/authorize",
            "token_endpoint": "https://idp.example/token",
            "userinfo_endpoint": "https://idp.example/userinfo",
            "client_id": "cid",
            "client_secret": "csec",
        },
    )
    base.update(overrides)
    return Settings(**base)


class FakeResult:
    """scripted execute() 返回值:第一路查询用 scalar_one_or_none,
    第二路(email)用 scalars().all()。"""

    def __init__(self, rows: list[User | None]) -> None:
        self._rows = rows

    def scalar_one_or_none(self) -> User | None:
        return self._rows[0] if self._rows else None

    def scalars(self) -> "FakeResult":
        return self

    def all(self) -> list[User | None]:
        return self._rows


class FakeSession:
    """只实现 upsert_user_from_userinfo 用到的 execute/commit/refresh/add。"""

    def __init__(self, scripted: list[FakeResult]) -> None:
        self._scripted = list(scripted)
        self.executes = 0
        self.commits = 0
        self.refreshes = 0
        self.added: list[User] = []

    async def execute(self, _stmt: Any) -> FakeResult:
        self.executes += 1
        return self._scripted.pop(0)

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, _obj: Any) -> None:
        self.refreshes += 1

    def add(self, obj: User) -> None:
        self.added.append(obj)


def make_local_user(**overrides: Any) -> User:
    base = dict(
        id=uuid.uuid4(),
        name="本地账号",
        email=LOCAL_EMAIL,
        username="chenxm",
        oidc_sub=None,
        is_active=True,
    )
    base.update(overrides)
    return User(**base)


# ─── upsert 分支 ─────────────────────────────────────────────────────────────
class TestUpsertUserFromUserinfo:
    async def test_sub_hit_returns_existing(self) -> None:
        """oidc_sub 直接命中 → 不落 email 兜底查询,字段同步。"""
        existing = make_local_user(oidc_sub=SUB)
        db = FakeSession([FakeResult([existing])])
        svc = OIDCService(make_settings())
        try:
            user = await svc.upsert_user_from_userinfo(
                db, {"sub": SUB, "name": NAME, "email": EMAIL}
            )
        finally:
            await svc.close()

        assert user is existing
        assert db.executes == 1, "sub 命中后不应再查 email"
        assert db.commits == 1
        assert user.name == NAME

    async def test_email_fallback_links_local_user(self) -> None:
        """F16 核心:sub miss + email 命中已有本地账号 → 补绑 oidc_sub,不重复建号。"""
        existing = make_local_user()  # oidc_sub=None
        db = FakeSession([FakeResult([]), FakeResult([existing])])
        svc = OIDCService(make_settings())
        try:
            user = await svc.upsert_user_from_userinfo(
                db, {"sub": SUB, "name": NAME, "email": EMAIL}
            )
        finally:
            await svc.close()

        assert user is existing
        assert user.oidc_sub == SUB, "email 关联后应补绑 oidc_sub"
        assert user.name == NAME
        assert db.added == [], "不应新建用户"
        assert db.commits == 1

    async def test_email_miss_creates_new_user(self) -> None:
        """sub + email 都 miss → 新建用户。"""
        db = FakeSession([FakeResult([]), FakeResult([])])
        svc = OIDCService(make_settings())
        try:
            user = await svc.upsert_user_from_userinfo(
                db, {"sub": SUB, "name": NAME, "email": EMAIL}
            )
        finally:
            await svc.close()

        assert db.added and db.added[0] is user
        assert user.oidc_sub == SUB
        assert user.email == EMAIL
        assert user.name == NAME
        assert user.is_active is True

    async def test_email_taken_by_other_oidc_sub_not_stolen(self) -> None:
        """email 命中但已绑其它 oidc_sub → 不抢账号,按新用户建号。"""
        other = make_local_user(oidc_sub="oidc-sub-other")
        db = FakeSession([FakeResult([]), FakeResult([other])])
        svc = OIDCService(make_settings())
        try:
            user = await svc.upsert_user_from_userinfo(
                db, {"sub": SUB, "name": NAME, "email": EMAIL}
            )
        finally:
            await svc.close()

        assert user is not other
        assert other.oidc_sub == "oidc-sub-other", "已有身份不能被覆盖"
        assert user.oidc_sub == SUB
        assert db.added == [user], "应新建独立账号"
