"""#150 本地用户/组管理后台集成测试 — 跑在 ms-api 容器里(`docker exec ms-api pytest`)。

预期前置(同 test_v4_permissions.py):
  1. seed_demo_data.py 已跑过(Evan = 真 user + org admin;outsider = fake)
  2. OpenFGA store / model 已 push
  3. env=dev(允许 X-User-Id header 模拟身份)

覆盖(issue #150 验收):
  - 非 system admin 访问 /admin/directory → 403
  - 创建用户 → 临时密码回显一次 + password_hash 已写 + must_change_password=true
  - 重名 username → 409
  - 组 CRUD + 重名 → 409
  - **建组 → 加人 → 组 viewer 挂 project → permissions.check 立即生效**;移出组立即失效
  - 禁用用户 → OpenFGA tuple 全撤 + is_active=false;启用 → 恢复 org member
  - admin 重置密码 → 新临时密码 + must_change_password
"""
from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app

# seed 写死的真 user / fake outsider(同 test_v4_permissions.py)
EVAN_ID = "3f1b659e-9ef1-4e65-aa03-4407ad7bcfc4"
OUTSIDER_ID = "00000000-0000-0000-0000-0000000000aa"
PROJECT_WEDDING = "11111111-1111-1111-1111-111111111101"   # private,seed 建


@pytest.fixture(scope="session")
async def app_with_lifespan():
    app = create_app()
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        yield app


@pytest.fixture(scope="session")
async def client(app_with_lifespan):
    transport = ASGITransport(app=app_with_lifespan)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _h(user_id: str) -> dict[str, str]:
    return {"X-User-Id": user_id}


def _uniq(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


# ─── 守门 ────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_directory_requires_system_admin(client: AsyncClient) -> None:
    r = await client.get("/api/v1/admin/directory/users", headers=_h(OUTSIDER_ID))
    assert r.status_code == 403, r.text
    r2 = await client.post(
        "/api/v1/admin/directory/users",
        json={"username": _uniq("nobody"), "name": "Nobody"},
        headers=_h(OUTSIDER_ID),
    )
    assert r2.status_code == 403


# ─── 用户 CRUD ───────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_create_user_returns_temp_password(client: AsyncClient) -> None:
    uname = _uniq("alice")
    r = await client.post(
        "/api/v1/admin/directory/users",
        json={"username": uname, "name": "Alice 测试", "email": f"{uname}@example.com"},
        headers=_h(EVAN_ID),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["username"] == uname
    assert body["is_active"] is True
    assert body["must_change_password"] is True
    assert len(body["temporary_password"]) >= 8
    assert "password_hash" not in body  # 不泄露 hash

    # 列表里能看到且不含 hash
    r2 = await client.get("/api/v1/admin/directory/users",
                          params={"q": uname}, headers=_h(EVAN_ID))
    assert r2.status_code == 200
    found = [u for u in r2.json() if u["username"] == uname]
    assert found and "password_hash" not in found[0]

    # /me 可见(本地用户无飞书字段也不崩)
    r3 = await client.get("/api/v1/auth/me", headers=_h(body["id"]))
    assert r3.status_code == 200, r3.text
    assert r3.json()["is_active"] is True


@pytest.mark.asyncio
async def test_create_user_duplicate_username_409(client: AsyncClient) -> None:
    uname = _uniq("dup")
    r = await client.post(
        "/api/v1/admin/directory/users",
        json={"username": uname, "name": "Dup One"}, headers=_h(EVAN_ID),
    )
    assert r.status_code == 201, r.text
    r2 = await client.post(
        "/api/v1/admin/directory/users",
        json={"username": uname, "name": "Dup Two"}, headers=_h(EVAN_ID),
    )
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_disable_revokes_tuples_and_enable_restores_org_member(
    client: AsyncClient, app_with_lifespan,
) -> None:
    uname = _uniq("carol")
    r = await client.post(
        "/api/v1/admin/directory/users",
        json={"username": uname, "name": "Carol"}, headers=_h(EVAN_ID),
    )
    assert r.status_code == 201, r.text
    uid = r.json()["id"]

    perms = app_with_lifespan.state.permissions
    # 禁用 → tuple 全撤
    r2 = await client.post(f"/api/v1/admin/directory/users/{uid}/disable", headers=_h(EVAN_ID))
    assert r2.status_code == 200, r2.text
    assert r2.json()["tuples_revoked"] == 1  # org member 那一条
    me = (await client.get("/api/v1/auth/me", headers=_h(uid))).json()
    assert me["is_active"] is False
    # OpenFGA store 直接核对:该 user 已无任何 tuple
    from openfga_sdk.models import TupleKey
    resp = await perms._client.read(TupleKey(user=f"user:{uid}"))
    assert resp.tuples == [], f"禁用后 store 应无该 user 的 tuple: {resp.tuples}"

    # 重复禁用 → 409
    r3 = await client.post(f"/api/v1/admin/directory/users/{uid}/disable", headers=_h(EVAN_ID))
    assert r3.status_code == 409

    # 禁用用户不能再加组(400)
    g = (await client.post(
        "/api/v1/admin/directory/groups",
        json={"name": _uniq("grp")}, headers=_h(EVAN_ID),
    )).json()
    r4 = await client.post(
        f"/api/v1/admin/directory/groups/{g['id']}/members",
        json={"user_id": uid}, headers=_h(EVAN_ID),
    )
    assert r4.status_code == 400

    # 启用 → 恢复 org member tuple + is_active
    r5 = await client.post(f"/api/v1/admin/directory/users/{uid}/enable", headers=_h(EVAN_ID))
    assert r5.status_code == 200, r5.text
    me2 = (await client.get("/api/v1/auth/me", headers=_h(uid))).json()
    assert me2["is_active"] is True


@pytest.mark.asyncio
async def test_reset_password(client: AsyncClient) -> None:
    uname = _uniq("dave")
    r = await client.post(
        "/api/v1/admin/directory/users",
        json={"username": uname, "name": "Dave"}, headers=_h(EVAN_ID),
    )
    assert r.status_code == 201
    uid = r.json()["id"]
    r2 = await client.post(
        f"/api/v1/admin/directory/users/{uid}/reset-password", headers=_h(EVAN_ID),
    )
    assert r2.status_code == 200, r2.text
    assert len(r2.json()["temporary_password"]) >= 8
    # 重置后强制改密
    r3 = await client.get("/api/v1/admin/directory/users", headers=_h(EVAN_ID))
    u = next(x for x in r3.json() if x["id"] == uid)
    assert u["must_change_password"] is True

    # 不存在的 user → 404
    r4 = await client.post(
        f"/api/v1/admin/directory/users/{uuid.uuid4()}/reset-password", headers=_h(EVAN_ID),
    )
    assert r4.status_code == 404


# ─── 组 CRUD + 成员 → 权限立即生效 ─────────────────────────────────────────
@pytest.mark.asyncio
async def test_group_crud_and_membership_enforces_permission(
    client: AsyncClient, app_with_lifespan,
) -> None:
    # 1) 建组
    gname = _uniq("editors")
    r = await client.post(
        "/api/v1/admin/directory/groups",
        json={"name": gname, "description": "剪辑组"}, headers=_h(EVAN_ID),
    )
    assert r.status_code == 201, r.text
    gid = r.json()["id"]
    assert r.json()["member_count"] == 0

    # 重名 → 409
    r_dup = await client.post(
        "/api/v1/admin/directory/groups",
        json={"name": gname}, headers=_h(EVAN_ID),
    )
    assert r_dup.status_code == 409

    # 2) 建用户 + 加入组
    uname = _uniq("editor")
    u = (await client.post(
        "/api/v1/admin/directory/users",
        json={"username": uname, "name": "Editor"}, headers=_h(EVAN_ID),
    )).json()
    uid = u["id"]
    r2 = await client.post(
        f"/api/v1/admin/directory/groups/{gid}/members",
        json={"user_id": uid}, headers=_h(EVAN_ID),
    )
    assert r2.status_code == 201, r2.text

    # 重复加 → 409
    r2dup = await client.post(
        f"/api/v1/admin/directory/groups/{gid}/members",
        json={"user_id": uid}, headers=_h(EVAN_ID),
    )
    assert r2dup.status_code == 409

    # 成员列表
    r3 = await client.get(f"/api/v1/admin/directory/groups/{gid}/members", headers=_h(EVAN_ID))
    assert r3.status_code == 200
    assert any(m["user_id"] == uid for m in r3.json())

    # 3) **验收:组 viewer 挂 private project → 成员立即 can_view**
    r4 = await client.post(
        f"/api/v1/projects/{PROJECT_WEDDING}/members",
        json={"group_id": gid, "role": "viewer"}, headers=_h(EVAN_ID),
    )
    assert r4.status_code == 200, r4.text
    r5 = await client.get(f"/api/v1/projects/{PROJECT_WEDDING}", headers=_h(uid))
    assert r5.status_code == 200, f"组 viewer 应立即可见: {r5.text}"

    # 4) 移出组 → 立即失效
    r6 = await client.delete(
        f"/api/v1/admin/directory/groups/{gid}/members/{uid}", headers=_h(EVAN_ID),
    )
    assert r6.status_code == 200, r6.text
    r7 = await client.get(f"/api/v1/projects/{PROJECT_WEDDING}", headers=_h(uid))
    assert r7.status_code == 403, "移出组后应立即失去 can_view"

    # 移出不存在的成员 → 404
    r8 = await client.delete(
        f"/api/v1/admin/directory/groups/{gid}/members/{uid}", headers=_h(EVAN_ID),
    )
    assert r8.status_code == 404

    # 5) 改组成员后删组
    r9 = await client.post(
        f"/api/v1/admin/directory/groups/{gid}/members",
        json={"user_id": uid}, headers=_h(EVAN_ID),
    )
    assert r9.status_code == 201
    r10 = await client.delete(f"/api/v1/admin/directory/groups/{gid}", headers=_h(EVAN_ID))
    assert r10.status_code == 200, r10.text
    # 组列表已无
    r11 = await client.get("/api/v1/admin/directory/groups",
                           params={"q": gname}, headers=_h(EVAN_ID))
    assert all(g["id"] != gid for g in r11.json())


# ─── GroupPicker 数据源本地化 ────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_groups_picker_returns_local_groups(client: AsyncClient) -> None:
    """GET /api/v1/groups 返本地 groups 表(不再转调飞书),带 member_count。"""
    gname = _uniq("picker")
    g = (await client.post(
        "/api/v1/admin/directory/groups",
        json={"name": gname, "description": "picker 测试"}, headers=_h(EVAN_ID),
    )).json()

    r = await client.get("/api/v1/groups", params={"q": gname}, headers=_h(EVAN_ID))
    assert r.status_code == 200, r.text
    items = r.json()
    hit = [x for x in items if x["id"] == g["id"]]
    assert len(hit) == 1
    assert hit[0]["name"] == gname
    assert hit[0]["member_count"] == 0
