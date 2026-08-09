"""本地账号密码登录(#149)集成测试 — 跑在 ms-api 容器内。

`docker exec ms-api pytest tests/ -v`;本地无 DB 时本模块自动 skip。

覆盖:login 成功失败 / 限流触发 / must_change_password 流转 / change-password。

注意:测试在共享容器里跑(与其他 3 个并行 agent 共用),fixture 自建用户 +
teardown 清理(用户行 + 限流 redis key),不污染 test_v4_permissions 依赖的 seed 数据。
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, text

from app.db.session import get_sessionmaker
from app.db.tables import User
from app.main import create_app
from app.services.local_auth import LocalAuthService
from app.settings import Settings

PASS_OK = "passw0rd"


def _uname(prefix: str) -> str:
    return f"it_{prefix}_{uuid.uuid4().hex[:8]}"


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
    )
    base.update(overrides)
    return Settings(**base)


_CLIENT: AsyncClient | None = None


@pytest.fixture(scope="session")
async def client():
    """拉起 app(lifespan);DB 不可达时整体跳过。

    注意:pytest-asyncio 会先初始化 session 级 fixture 再跑 module 级,
    所以 DB 探测必须放在本 fixture 内(而不是 module 级 autouse),否则
    lifespan 先于探测执行。用一次性 engine,避免污染 app 级 engine pool。
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.settings import get_settings

    engine = create_async_engine(str(get_settings().db_url))
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        await engine.dispose()
    except Exception as exc:
        await engine.dispose()
        pytest.skip(f"no reachable DB — integration tests skipped: {exc}")

    global _CLIENT
    app = create_app()
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            _CLIENT = ac
            yield ac
            _CLIENT = None


@pytest.fixture(autouse=True)
def _clear_cookies_after_test():
    """session 级 client 跨测试留 cookie(stateless JWT 不过期)会串测试,逐个清。

    同时清掉共享 IP("testclient")的限流计数 —— ASGI client 所有请求同 IP,
    不清的话上个测试的失败计数会污染下个测试(IP 维度提前触发锁)。
    不直接依赖 client fixture(避免把集成 client 拉进不需要它的场景)。
    """
    yield
    if _CLIENT is not None:
        _CLIENT.cookies.clear()
    try:
        from redis.asyncio import from_url

        from app.services.local_auth import _FAIL_IP_KEY, _LOCK_IP_KEY
        from app.settings import get_settings

        redis = from_url(str(get_settings().redis_url), decode_responses=True)
        try:
            asyncio.run(redis.delete(
                _FAIL_IP_KEY.format(ip="testclient"),
                _LOCK_IP_KEY.format(ip="testclient"),
            ))
        finally:
            asyncio.run(redis.aclose())
    except Exception:
        pass


@pytest.fixture
async def make_user():
    """创建本地账号用户;teardown 删用户行 + 清本测试涉及的限流 key。"""
    created: list[tuple[User, str]] = []

    async def _make(
        *,
        name: str | None = None,
        username: str | None = None,
        email: str | None = None,
        password: str | None = PASS_OK,
        must_change: bool = True,
        is_active: bool = True,
    ) -> tuple[User, str]:
        """建用户。返回 (User, login_key):login_key = username(给了的话)或 name 兜底。

        username=None 时模拟老飞书用户(只 name/email 可登);
        username 给定时模拟 #150 管理后台建号形态(F2 review 主路径)。
        """
        uname = _uname("user")
        svc = LocalAuthService(make_settings(), _FakeRedis())  # type: ignore[arg-type]
        async with get_sessionmaker()() as db:
            u = User(
                feishu_open_id=f"ou_it_{uuid.uuid4().hex}",
                name=name or uname,
                username=username,
                email=email or f"{uname}@example.com",
                is_active=is_active,
                must_change_password=must_change,
                password_hash=None if password is None else svc.hash_password(password),
            )
            db.add(u)
            await db.commit()
            await db.refresh(u)
            created.append((u, username or uname))
            return u, username or uname

    yield _make

    # teardown:删用户行(审计行 actor FK 是 SET NULL,安全)+ 清限流 key
    async def _cleanup() -> None:
        from redis.asyncio import from_url

        from app.services.local_auth import (
            _FAIL_IP_KEY,
            _FAIL_USER_KEY,
            _LOCK_IP_KEY,
            _LOCK_USER_KEY,
        )
        from app.settings import get_settings

        async with get_sessionmaker()() as db:
            for u, _ in created:
                await db.execute(delete(User).where(User.id == u.id))
            await db.commit()
        redis = from_url(str(get_settings().redis_url), decode_responses=True)
        keys = [_FAIL_IP_KEY.format(ip="testclient"), _LOCK_IP_KEY.format(ip="testclient")]
        for _, key in created:
            keys += [
                _FAIL_USER_KEY.format(username=key.lower()),
                _LOCK_USER_KEY.format(username=key.lower()),
            ]
        await redis.delete(*keys)
        await redis.aclose()

    await _cleanup()


class _FakeRedis:
    """make_user 里只用来产 argon2 哈希,不碰网络。"""

    async def get(self, key: str) -> str | None:
        return None

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        pass

    async def delete(self, *keys: str) -> None:
        pass

    async def incr(self, key: str) -> int:
        return 1

    async def expire(self, key: str, seconds: int) -> None:
        pass

    def pipeline(self) -> _FakePipeline:
        return _FakePipeline()


class _FakePipeline:
    async def execute(self) -> list[Any]:
        return [1, 1, 1, 1]


async def _flush_auth_user_keys() -> None:
    """SCAN 清 auth:fail:user:* / auth:lock:user:*(测试产生的 ghost key 兜底)。"""
    from redis.asyncio import from_url

    from app.settings import get_settings

    redis = from_url(str(get_settings().redis_url), decode_responses=True)
    try:
        async for key in redis.scan_iter(match="auth:fail:user:*"):
            await redis.delete(key)
        async for key in redis.scan_iter(match="auth:lock:user:*"):
            await redis.delete(key)
    finally:
        await redis.aclose()


# ─── login 成功/失败 ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_login_success_sets_cookie_and_must_change(client: AsyncClient, make_user) -> None:
    u, uname = await make_user()
    r = await client.post("/api/v1/auth/local/login",
                          json={"username": uname, "password": PASS_OK})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert body["user_id"] == str(u.id)
    assert body["must_change_password"] is True
    # cookie 设置照抄 OIDC callback(httponly + path=/)
    assert "ms_session" in r.cookies

    # 带 cookie 的 /me 应回报有效 must_change_password(password 已设)
    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["must_change_password"] is True
    assert me.json()["password_set"] is True


@pytest.mark.asyncio
async def test_login_by_email(client: AsyncClient, make_user) -> None:
    u, _ = await make_user()
    r = await client.post("/api/v1/auth/local/login",
                          json={"username": u.email, "password": PASS_OK})
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_login_name_case_insensitive(client: AsyncClient, make_user) -> None:
    await make_user(name="ZhangSan")
    r = await client.post("/api/v1/auth/local/login",
                          json={"username": "zhangsan", "password": PASS_OK})
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient, make_user) -> None:
    _, uname = await make_user()
    r = await client.post("/api/v1/auth/local/login",
                          json={"username": uname, "password": "wrong1x"})
    assert r.status_code == 401
    assert "用户名或密码错误" in r.json()["detail"]


@pytest.mark.asyncio
async def test_login_unknown_user(client: AsyncClient) -> None:
    r = await client.post("/api/v1/auth/local/login",
                          json={"username": _uname("ghost"), "password": PASS_OK})
    assert r.status_code == 401
    assert "用户名或密码错误" in r.json()["detail"]


@pytest.mark.asyncio
async def test_login_inactive_user(client: AsyncClient, make_user) -> None:
    _, uname = await make_user(is_active=False)
    r = await client.post("/api/v1/auth/local/login",
                          json={"username": uname, "password": PASS_OK})
    assert r.status_code == 403
    assert "禁用" in r.json()["detail"]


@pytest.mark.asyncio
async def test_login_user_without_local_password(client: AsyncClient, make_user) -> None:
    """存量飞书用户(无本地密码)登录本地通道 → 统一 401,不泄露无密码事实。"""
    _, uname = await make_user(password=None)
    r = await client.post("/api/v1/auth/local/login",
                          json={"username": uname, "password": PASS_OK})
    assert r.status_code == 401
    assert "用户名或密码错误" in r.json()["detail"]


@pytest.mark.asyncio
async def test_me_must_change_false_without_password(client: AsyncClient, make_user) -> None:
    """无本地密码的用户 /me 不得报 must_change_password(避免前端误跳改密页)。"""
    u, _ = await make_user(password=None)  # must_change_password 默认 true
    assert u.must_change_password is True
    r = await client.get("/api/v1/auth/me", headers={"X-User-Id": str(u.id)})
    assert r.status_code == 200
    assert r.json()["must_change_password"] is False
    assert r.json()["password_set"] is False


@pytest.mark.asyncio
async def test_login_ambiguous_name_rejected(client: AsyncClient, make_user) -> None:
    """name 重复时拒绝登录(防歧义),返回统一 401。"""
    await make_user(name="Duplicated")
    await make_user(name="Duplicated")
    r = await client.post("/api/v1/auth/local/login",
                          json={"username": "Duplicated", "password": PASS_OK})
    assert r.status_code == 401


# ─── 限流触发 ────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_rate_limit_username_locks_even_with_correct_password(
    client: AsyncClient, make_user,
) -> None:
    _, uname = await make_user()
    for _ in range(5):
        r = await client.post("/api/v1/auth/local/login",
                              json={"username": uname, "password": "wrong1x"})
        assert r.status_code == 401
    # 第 6 次即使密码正确也 429
    r = await client.post("/api/v1/auth/local/login",
                          json={"username": uname, "password": PASS_OK})
    assert r.status_code == 429
    assert "锁定" in r.json()["detail"]


@pytest.mark.asyncio
async def test_rate_limit_ip_dimension(client: AsyncClient, make_user) -> None:
    """同一 IP 5 个不同用户名连续失败 → IP 维度锁定。"""
    for _ in range(5):
        await make_user()
    for i in range(5):
        r = await client.post("/api/v1/auth/local/login",
                              json={"username": f"it_ghost_{i}_{uuid.uuid4().hex[:8]}",
                                    "password": "wrong1x"})
        assert r.status_code == 401
    r = await client.post("/api/v1/auth/local/login",
                          json={"username": _uname("locked"), "password": "whatever1"})
    assert r.status_code == 429
    # ghost username 的计数 key 不在 make_user 记录里,手动清掉
    await _flush_auth_user_keys()


# ─── must_change_password 流转 + change-password ─────────────────────────────
@pytest.mark.asyncio
async def test_change_password_flow(client: AsyncClient, make_user) -> None:
    """登录 → 改密(错误旧密码/弱新密码被拒)→ 新密码再登录 → must_change=false。"""
    _, uname = await make_user()
    r = await client.post("/api/v1/auth/local/login",
                          json={"username": uname, "password": PASS_OK})
    assert r.status_code == 200

    new_pw = "newPass123"
    # 错误旧密码 → 400
    r = await client.post("/api/v1/auth/change-password",
                          json={"old_password": "wrong-old", "new_password": new_pw})
    assert r.status_code == 400
    # 弱新密码 → 400
    r = await client.post("/api/v1/auth/change-password",
                          json={"old_password": PASS_OK, "new_password": "123"})
    assert r.status_code == 400
    # 新密码 == 旧密码 → 400
    r = await client.post("/api/v1/auth/change-password",
                          json={"old_password": PASS_OK, "new_password": PASS_OK})
    assert r.status_code == 400
    # 合法改密 → 200
    r = await client.post("/api/v1/auth/change-password",
                          json={"old_password": PASS_OK, "new_password": new_pw})
    assert r.status_code == 200, r.text
    # 改密后 /me 不再要求强制改密
    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["must_change_password"] is False
    # 新密码登录成功
    r = await client.post("/api/v1/auth/local/login",
                          json={"username": uname, "password": new_pw})
    assert r.status_code == 200, r.text
    # 旧密码不再可用
    r = await client.post("/api/v1/auth/local/login",
                          json={"username": uname, "password": PASS_OK})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_change_password_requires_auth(client: AsyncClient) -> None:
    r = await client.post("/api/v1/auth/change-password",
                          json={"old_password": "x", "new_password": "y"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_change_password_without_local_password(client: AsyncClient, make_user) -> None:
    """存量飞书用户(无本地密码)改密 → 400 指引走管理后台初始化。"""
    u, _ = await make_user(password=None)
    r = await client.post("/api/v1/auth/change-password",
                          headers={"X-User-Id": str(u.id)},
                          json={"old_password": "whatever1", "new_password": "newPass123"})
    assert r.status_code == 400
    assert "尚未设置本地密码" in r.json()["detail"]


# ─── F2 review:username 列参与登录匹配 ──────────────────────────────────────
@pytest.mark.asyncio
async def test_login_by_username(client: AsyncClient, make_user) -> None:
    """管理后台建号形态(有 username)→ 按 username 登录成功。"""
    u, _ = await make_user(username=_uname("zhang"))
    r = await client.post("/api/v1/auth/local/login",
                          json={"username": u.username, "password": PASS_OK})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_login_username_case_insensitive(client: AsyncClient, make_user) -> None:
    u, _ = await make_user(username=_uname("zhang"))
    r = await client.post("/api/v1/auth/local/login",
                          json={"username": (u.username or "").upper(), "password": PASS_OK})
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_login_username_priority_over_ambiguous_name(
    client: AsyncClient, make_user,
) -> None:
    """两人 name 重名:按 name 登录 401(歧义拒绝);按各自 username 登录都 200。"""
    u1, _ = await make_user(name="张三", username=_uname("zhang"))
    u2, _ = await make_user(name="张三", username=_uname("zhang"))
    assert u1.username != u2.username
    r_name = await client.post("/api/v1/auth/local/login",
                               json={"username": "张三", "password": PASS_OK})
    assert r_name.status_code == 401, r_name.text
    for un in (u1.username, u2.username):
        r = await client.post("/api/v1/auth/local/login",
                              json={"username": un, "password": PASS_OK})
        assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_e2e_directory_created_user_can_login(client: AsyncClient) -> None:
    """F2 端到端:管理后台建号 → 用返回的 username + temporary_password 登录。

    走真实链路:POST /admin/directory/users(seed Evan = system admin,
    X-User-Id 仅 dev 容器生效)→ 返回 username + 临时密码 → cookie 登录。
    """
    uname = _uname("zhang")
    try:
        r = await client.post(
            "/api/v1/admin/directory/users",
            headers={"X-User-Id": "3f1b659e-9ef1-4e65-aa03-4407ad7bcfc4"},  # seed Evan
            json={"username": uname, "name": "张三", "email": None},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["username"] == uname
        assert body["temporary_password"], "应回显一次性临时密码"

        r2 = await client.post(
            "/api/v1/auth/local/login",
            json={"username": uname, "password": body["temporary_password"]},
        )
        assert r2.status_code == 200, r2.text
        j = r2.json()
        assert j["status"] == "ok"
        assert j["must_change_password"] is True, "新建用户应强制首登改密"
    finally:
        async with get_sessionmaker()() as db:
            await db.execute(delete(User).where(User.username == uname))
            await db.commit()


# ─── F15 review:must_change_password 后端强制拦截 ──────────────────────────
@pytest.mark.asyncio
async def test_forced_change_blocks_other_endpoints(
    client: AsyncClient, make_user,
) -> None:
    """未改密时:受保护端点 403;/me 与改密放行;改密后放行。"""
    _, uname = await make_user()  # must_change=True(default)
    r = await client.post("/api/v1/auth/local/login",
                          json={"username": uname, "password": PASS_OK})
    assert r.status_code == 200

    # 非改密端点 → 403(后端强制,防绕过前端守卫)
    r2 = await client.get("/api/v1/projects")
    assert r2.status_code == 403, r2.text
    assert "新密码" in r2.text

    # /me 放行(前端守卫靠它识别强制状态)
    r3 = await client.get("/api/v1/auth/me")
    assert r3.status_code == 200, r3.text

    # 改密成功 → 解除强制
    r4 = await client.post("/api/v1/auth/change-password",
                           json={"old_password": PASS_OK, "new_password": "newpass1"})
    assert r4.status_code == 200, r4.text
    r5 = await client.get("/api/v1/projects")
    assert r5.status_code == 200, r5.text
    assert r5.json() is not None


@pytest.mark.asyncio
async def test_forced_change_dev_header_not_blocked(client: AsyncClient, make_user) -> None:
    """dev 通道(X-User-Id)不做强制改密拦截 — 本地开发无密码流程。"""
    u, _ = await make_user()  # must_change=True
    r = await client.get("/api/v1/projects", headers={"X-User-Id": str(u.id)})
    assert r.status_code == 200, r.text
