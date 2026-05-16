"""Phase B-1 smoke test:healthz endpoint。"""
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest.mark.asyncio
async def test_healthz() -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "version" in body


@pytest.mark.asyncio
async def test_router_stubs() -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        for router_name in ["auth", "projects", "assets", "approvals", "webhooks", "admin"]:
            resp = await ac.get(f"/api/v1/{router_name}/_stub")
            assert resp.status_code == 200
            assert resp.json() == {"router": router_name, "status": "stub - not implemented yet"}
