"""本地账号密码登录(#149)单元测试 — 无基础设施(哈希 / 策略 / 限流 FakeRedis)。

集成测试见 tests/test_local_auth_integration.py(容器内跑)。
"""
from __future__ import annotations

from typing import Any

from app.services.local_auth import LocalAuthService
from app.settings import Settings

PASS_OK = "passw0rd"


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
    )
    base.update(overrides)
    return Settings(**base)


class FakeRedis:
    """LocalAuthService 用到的 redis.asyncio 接口子集。"""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self._ttl: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._store[key] = value
        if ex is not None:
            self._ttl[key] = ex

    async def delete(self, *keys: str) -> None:
        for k in keys:
            self._store.pop(k, None)
            self._ttl.pop(k, None)

    async def incr(self, key: str) -> int:
        nxt = int(self._store.get(key, 0)) + 1
        self._store[key] = str(nxt)
        return nxt

    async def expire(self, key: str, seconds: int) -> None:
        self._ttl[key] = seconds

    def pipeline(self) -> FakePipeline:
        return FakePipeline(self)


class FakePipeline:
    def __init__(self, redis: FakeRedis) -> None:
        self._redis = redis
        self._cmds: list[tuple[str, Any]] = []

    def incr(self, key: str) -> FakePipeline:
        self._cmds.append(("incr", key))
        return self

    def expire(self, key: str, seconds: int) -> FakePipeline:
        self._cmds.append(("expire", key, seconds))
        return self

    async def execute(self) -> list[Any]:
        out: list[Any] = []
        for cmd in self._cmds:
            if cmd[0] == "incr":
                out.append(await self._redis.incr(cmd[1]))
            else:
                out.append(await self._redis.expire(cmd[1], cmd[2]))
        self._cmds = []
        return out


def make_service(**overrides: Any) -> tuple[LocalAuthService, FakeRedis]:
    redis = FakeRedis()
    return LocalAuthService(make_settings(**overrides), redis), redis  # type: ignore[arg-type]


# ─── 单元:密码哈希 ────────────────────────────────────────────────────────────
class TestPasswordHashing:
    def test_roundtrip(self) -> None:
        svc, _ = make_service()
        h = svc.hash_password(PASS_OK)
        assert h.startswith("$argon2id$"), "必须用 argon2id"
        assert svc.verify_password(PASS_OK, h) is True

    def test_wrong_password_false(self) -> None:
        svc, _ = make_service()
        h = svc.hash_password(PASS_OK)
        assert svc.verify_password("wrong-pass", h) is False

    def test_same_password_hashes_differ(self) -> None:
        """argon2 带随机 salt,同一密码两次哈希不同。"""
        svc, _ = make_service()
        assert svc.hash_password(PASS_OK) != svc.hash_password(PASS_OK)

    def test_invalid_hash_false(self) -> None:
        """库里混入非 argon2 格式哈希(如明文)时不抛,返回 False。"""
        svc, _ = make_service()
        assert svc.verify_password(PASS_OK, "not-an-argon2-hash") is False


# ─── 单元:密码策略 ────────────────────────────────────────────────────────────
class TestPasswordPolicy:
    def test_too_short(self) -> None:
        svc, _ = make_service()
        assert svc.validate_password_policy("a1") is not None

    def test_missing_letter(self) -> None:
        svc, _ = make_service()
        assert svc.validate_password_policy("12345678") is not None

    def test_missing_digit(self) -> None:
        svc, _ = make_service()
        assert svc.validate_password_policy("abcdefgh") is not None

    def test_valid(self) -> None:
        svc, _ = make_service()
        assert svc.validate_password_policy(PASS_OK) is None

    def test_min_length_from_settings(self) -> None:
        svc, _ = make_service(auth_password_min_length=10)
        assert svc.validate_password_policy("abc12345") is not None
        assert svc.validate_password_policy("abc1234567") is None


# ─── 单元:限流(FakeRedis)───────────────────────────────────────────────────
class TestRateLimit:
    async def test_not_locked_initially(self) -> None:
        svc, _ = make_service()
        assert await svc.is_locked("1.2.3.4", "zhangsan") is False

    async def test_failures_below_threshold_not_locked(self) -> None:
        svc, _ = make_service()
        for _ in range(4):
            await svc.record_failure("1.2.3.4", "zhangsan")
        assert await svc.is_locked("1.2.3.4", "zhangsan") is False

    async def test_fifth_failure_locks_username(self) -> None:
        svc, _ = make_service()
        for _ in range(5):
            await svc.record_failure("1.2.3.4", "zhangsan")
        assert await svc.is_locked("1.2.3.4", "zhangsan") is True
        # 换 IP 也一样锁(per username 维度)
        assert await svc.is_locked("9.9.9.9", "zhangsan") is True

    async def test_ip_dimension_locks_all_usernames(self) -> None:
        svc, _ = make_service()
        for i in range(5):
            await svc.record_failure("1.2.3.4", f"user{i}")
        assert await svc.is_locked("1.2.3.4", "someone-else") is True
        # 其他 IP 不受影响
        assert await svc.is_locked("9.9.9.9", "someone-else") is False

    async def test_reset_clears_counters(self) -> None:
        svc, _ = make_service()
        for _ in range(4):
            await svc.record_failure("1.2.3.4", "zhangsan")
        await svc.reset_failures("1.2.3.4", "zhangsan")
        for _ in range(4):
            await svc.record_failure("1.2.3.4", "zhangsan")
        assert await svc.is_locked("1.2.3.4", "zhangsan") is False, "reset 后应从零重新计数"

    async def test_username_case_insensitive_key(self) -> None:
        svc, _ = make_service()
        for _ in range(5):
            await svc.record_failure("1.2.3.4", "ZhangSan")
        assert await svc.is_locked("1.2.3.4", "zhangsan") is True, "大小写不同应命中同一计数"


# ─── 单元:settings 默认值 ──────────────────────────────────────────────────
class TestSettingsDefaults:
    def test_session_ttl_default_7d(self) -> None:
        assert make_settings().session_jwt_ttl_seconds == 7 * 24 * 3600

    def test_rate_limit_defaults(self) -> None:
        s = make_settings()
        assert s.auth_max_failures == 5
        assert s.auth_lock_seconds == 15 * 60
