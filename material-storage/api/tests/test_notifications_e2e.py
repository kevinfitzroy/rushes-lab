"""#153 应用内通知中心 — 容器内全链路 e2e。

覆盖验收主链路:
  申请 → admin 收到待审通知 → 审批 → 申请人收到结果通知
  + SMTP 留空时零报错(no-op)

在容器环境跑(需 seed 固定用户 + OpenFGA store 就绪,参照 test_v4_permissions.py):
    docker exec ms-api pytest tests/test_notifications_e2e.py -v
本机 DB 不可达时自动 skip —— 门控与 test_local_auth_integration.py 同款。
"""
from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.settings import get_settings


@pytest.fixture(scope="session")
async def client():
    """拉起 app(含 lifespan);DB 不可达时跳过。

    **必须 session 级**:pyproject 里 asyncio loop scope 是 session,而 asyncpg
    连接不能跨 loop。function 级 fixture 每个用例新建 engine 却共享同一 session
    loop,查库会失败 —— 表现是 get_current_user 拿不到用户、接口一律 401。
    与 test_v4_permissions / test_local_auth_integration 的做法保持一致。

    原先这里是 `pytestmark = skipif(True, ...)` —— 硬编码常量,意味着**在任何环境
    都不会执行**,连容器内也跳过,于是 #153 的全链路验收从未真正跑过。改为与
    test_local_auth_integration.py 同款的 DB 可达性门控。

    另外必须进 lifespan:通知写入口依赖 app.state 上的 permissions / arq_pool / redis,
    不拉 lifespan 的话即使跑起来也会在 BackgroundTask 里炸。
    """
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(str(get_settings().db_url))
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        await engine.dispose()
    except Exception as exc:
        await engine.dispose()
        pytest.skip(f"no reachable DB — integration tests skipped: {exc}")

    app = create_app()
    async with (
        app.router.lifespan_context(app),  # type: ignore[attr-defined]
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac,
    ):
        yield ac


def _auth_headers(user_id: uuid.UUID) -> dict[str, str]:
    """dev 通道:仅 settings.env == 'dev' 时生效。"""
    return {"X-User-Id": str(user_id)}


async def test_full_chain_approval_notifications(client: AsyncClient) -> None:
    """申请 → admin 待审通知 → 审批 → 申请人结果通知(全链路)。"""
    settings = get_settings()
    if settings.env != "dev":
        pytest.skip("e2e 需 dev env 的 X-User-Id 通道;生产环境请用真实登录")

    # 契约账号来自 scripts/dev_bootstrap.py(alice=org admin,bob=普通成员,
    # project ...0b1 = dev-project)。原先写的 ...0a2 / ...0a3 在任何 seed 里都
    # 不存在 —— 配合 skipif(True) 一直没暴露,一跑就是 401「用户不存在」。
    admin_id = uuid.UUID("00000000-0000-0000-0000-000000000001")      # alice
    applicant_id = uuid.UUID("00000000-0000-0000-0000-000000000002")  # bob
    target_project_id = uuid.UUID("00000000-0000-0000-0000-0000000000b1")

    # 0) 基线:两人都无通知
    r = await client.get("/api/v1/notifications", headers=_auth_headers(admin_id))
    assert r.status_code == 200
    admin_unread_0 = r.json()["unread_count"]

    # 1) 申请人提交申请
    r = await client.post("/api/v1/approvals", json={
        "target_type": "project",
        "target_id": str(target_project_id),
        "action": "download",
        "duration_seconds": 3600,
        "reason": "e2e 通知链路测试",
    }, headers=_auth_headers(applicant_id))
    assert r.status_code == 201
    approval_id = r.json()["id"]

    # 2) admin 收到待审通知
    r = await client.get("/api/v1/notifications", headers=_auth_headers(admin_id))
    assert r.status_code == 200
    body = r.json()
    assert body["unread_count"] == admin_unread_0 + 1
    pending = [n for n in body["items"] if n["kind"] == "approval_pending"]
    assert any(n["title"] and "申请" in n["title"] for n in pending)

    # 3) admin 审批通过
    r = await client.post(
        f"/api/v1/approvals/{approval_id}/approve",
        json={"decision_note": "e2e ok"},
        headers=_auth_headers(admin_id),
    )
    assert r.status_code == 200

    # 4) 申请人收到结果通知
    r = await client.get("/api/v1/notifications", headers=_auth_headers(applicant_id))
    assert r.status_code == 200
    body = r.json()
    decided = [n for n in body["items"] if n["kind"] == "approval_decided"]
    assert any("已通过" in n["title"] for n in decided)

    # 5) mark-read 闭环
    first_id = decided[0]["id"]
    r = await client.post(
        "/api/v1/notifications/mark-read", json={"ids": [first_id]},
        headers=_auth_headers(applicant_id),
    )
    assert r.status_code == 200
    assert r.json()["updated"] >= 1
    r = await client.get("/api/v1/notifications", headers=_auth_headers(applicant_id))
    read = [n for n in r.json()["items"] if n["id"] == first_id]
    assert read and read[0]["read_at"] is not None


async def test_smtp_unconfigured_noop(client: AsyncClient) -> None:
    """SMTP 留空 = no-op 零报错(验收硬项):写通知不炸、接口正常。"""
    settings = get_settings()
    assert settings.smtp_enabled is False  # 本环境未配 SMTP
    if settings.env != "dev":
        pytest.skip("e2e 需 dev env 的 X-User-Id 通道;生产环境请用真实登录")
    uid = uuid.UUID("00000000-0000-0000-0000-000000000001")  # alice(dev_bootstrap)
    r = await client.get("/api/v1/notifications", headers=_auth_headers(uid))
    assert r.status_code == 200
    assert "unread_count" in r.json()
