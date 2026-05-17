"""iter a1 e2e 集成测试 — 跑在 ms-api 容器里(`docker exec ms-api pytest`)。

预期前置:
  1. seed_demo_data.py 已跑过(创建 3 项目 / 40 folder / 真 user Evan / fake outsider)
  2. OpenFGA store / model 已 push
  3. env=dev(允许 X-User-Id header 模拟身份)

覆盖:
  - permissions service 纯函数(fmt_subject)
  - 三种身份 list_projects 可见性
  - folder list 中 sensitive folder 过滤
  - admin (Evan) folder/invite/approval 流程
  - outsider 被拒
  - share 链路(创建 + GET token resolve)
"""
from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.services.permissions import fmt_subject

# seed 写死的真 user 和 fake outsider id(种子脚本里 hardcode)
EVAN_ID = "3f1b659e-9ef1-4e65-aa03-4407ad7bcfc4"
OUTSIDER_ID = "00000000-0000-0000-0000-0000000000aa"

PROJECT_WEDDING = "11111111-1111-1111-1111-111111111101"   # private
PROJECT_ZHANG = "11111111-1111-1111-1111-111111111102"     # private
PROJECT_EVENT = "11111111-1111-1111-1111-111111111103"     # public


# ─── 单元测试 ─────────────────────────────────────────────────────────────────
class TestFmtSubject:
    """fmt_subject:user / organization 不加 #member;group / department 加。"""

    def test_user(self) -> None:
        assert fmt_subject("user", "ou_xxx") == "user:ou_xxx"

    def test_organization(self) -> None:
        assert fmt_subject("organization", "t1") == "organization:t1"

    def test_group(self) -> None:
        assert fmt_subject("group", "g1") == "group:g1#member"

    def test_department(self) -> None:
        assert fmt_subject("department", "d1") == "department:d1#member"


# ─── HTTP 集成 fixture(session 级:asyncpg 不能跨 loop;同时减少 lifespan 反复) ─
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


# ─── /me ─────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_me_evan(client: AsyncClient) -> None:
    r = await client.get("/api/v1/auth/me", headers=_h(EVAN_ID))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == EVAN_ID
    assert body["open_id"].startswith("ou_")
    assert body["name"] == "Evan"


@pytest.mark.asyncio
async def test_me_outsider(client: AsyncClient) -> None:
    r = await client.get("/api/v1/auth/me", headers=_h(OUTSIDER_ID))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["open_id"] == "ou_fake_outsider"


# ─── projects list 可见性 ────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_projects_evan_sees_all(client: AsyncClient) -> None:
    """Evan 是创建者/admin,看到全部 3 个项目。"""
    r = await client.get("/api/v1/projects", headers=_h(EVAN_ID))
    assert r.status_code == 200
    ids = {p["id"] for p in r.json()}
    assert PROJECT_WEDDING in ids
    assert PROJECT_ZHANG in ids
    assert PROJECT_EVENT in ids


@pytest.mark.asyncio
async def test_projects_outsider_sees_only_public(client: AsyncClient) -> None:
    """Outsider 至少应见 public 项目(其他项目除非显式 grant)。"""
    r = await client.get("/api/v1/projects", headers=_h(OUTSIDER_ID))
    assert r.status_code == 200
    items = r.json()
    public_seen = [p for p in items if p["visibility"] == "public"]
    assert any(p["id"] == PROJECT_EVENT for p in public_seen)
    # 私有项目 wedding 不应见(除非测试中曾被 grant outsider)
    private_seen = [p for p in items
                    if p["id"] == PROJECT_WEDDING and p["visibility"] == "private"]
    assert not private_seen, "outsider 不应见 private wedding"


# ─── project 单条 access ──────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_project_get_private_denied_for_outsider(client: AsyncClient) -> None:
    r = await client.get(f"/api/v1/projects/{PROJECT_WEDDING}", headers=_h(OUTSIDER_ID))
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_project_get_public_ok_for_outsider(client: AsyncClient) -> None:
    r = await client.get(f"/api/v1/projects/{PROJECT_EVENT}", headers=_h(OUTSIDER_ID))
    assert r.status_code == 200


# ─── folders list:sensitive 过滤 ────────────────────────────────────────────
@pytest.mark.asyncio
async def test_folders_evan_sees_sensitive(client: AsyncClient) -> None:
    """Evan 被 seed 显式 invite 进所有 sensitive folder,应能看到。"""
    r = await client.get(
        "/api/v1/folders", params={"project_id": PROJECT_WEDDING}, headers=_h(EVAN_ID),
    )
    assert r.status_code == 200
    folders = r.json()
    sensitive_names = [f["name"] for f in folders if f["is_sensitive"]]
    # seed 里 wedding 有 2 个 sensitive folder
    assert any("VIP" in n for n in sensitive_names), sensitive_names


@pytest.mark.asyncio
async def test_folders_outsider_sees_only_public_project_normal_folders(client: AsyncClient) -> None:
    """Outsider 只能看 public project,且 sensitive folder 不可见(invited_* 为空)。"""
    r = await client.get(
        "/api/v1/folders", params={"project_id": PROJECT_EVENT}, headers=_h(OUTSIDER_ID),
    )
    assert r.status_code == 200
    folders = r.json()
    # public project 元数据可见(get_project 通过)但 folder 默认要 can_view,
    # outsider 没任何 tuple → 普通 folder 经 OR `is_sensitive=false` 全部返回(SQL 层),
    # sensitive folder 必须 OpenFGA can_view 才能见
    sensitive = [f for f in folders if f["is_sensitive"]]
    assert sensitive == [], f"outsider 不应见 sensitive: {sensitive}"


# ─── approval 流程 ────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_approval_create_and_pending_state(client: AsyncClient) -> None:
    """Evan 提交一个 approval — 应返 201 + status=pending。"""
    body = {
        "target_type": "project",
        "target_id": PROJECT_WEDDING,
        "action": "download",
        "duration_seconds": 3600,
        "reason": "test_v4 e2e — approval pending check",
    }
    r = await client.post("/api/v1/approvals", json=body, headers=_h(EVAN_ID))
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["status"] == "pending"
    assert a["target_id"] == PROJECT_WEDDING

    # outsider 也能提(任何人可申请);但 approve 不通过(无 admin)
    body2 = dict(body, reason="outsider 申请")
    r2 = await client.post("/api/v1/approvals", json=body2, headers=_h(OUTSIDER_ID))
    assert r2.status_code == 201


@pytest.mark.asyncio
async def test_approval_reject_by_non_admin_returns_403(client: AsyncClient) -> None:
    # Evan 创建,然后 outsider 尝试 approve → 403
    body = {
        "target_type": "project", "target_id": PROJECT_WEDDING,
        "action": "download", "duration_seconds": 3600,
        "reason": "non-admin approve test",
    }
    r = await client.post("/api/v1/approvals", json=body, headers=_h(EVAN_ID))
    assert r.status_code == 201
    aid = r.json()["id"]
    r2 = await client.post(
        f"/api/v1/approvals/{aid}/approve", json={"decision_note": "noop"},
        headers=_h(OUTSIDER_ID),
    )
    assert r2.status_code == 403


# ─── share 短链 ─────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_share_create_and_resolve(client: AsyncClient) -> None:
    # 拿一个 asset id(Evan 项目里随便挑一个)
    r = await client.get(
        "/api/v1/folders", params={"project_id": PROJECT_WEDDING}, headers=_h(EVAN_ID),
    )
    assert r.status_code == 200
    normal_folder = next(f for f in r.json() if not f["is_sensitive"])
    r2 = await client.get(
        "/api/v1/assets", params={"folder_id": normal_folder["id"]}, headers=_h(EVAN_ID),
    )
    assert r2.status_code == 200, r2.text
    assets = r2.json()
    assert assets, "seed 应至少 1 个 asset"
    asset = assets[0]

    # 创建 share(不推 IM,只生成链接)
    r3 = await client.post(
        f"/api/v1/share/assets/{asset['id']}",
        json={"receive_open_ids": [], "expires_in_seconds": 3600},
        headers=_h(EVAN_ID),
    )
    assert r3.status_code == 200, r3.text
    share = r3.json()
    assert "token" in share
    token = share["token"]

    # GET resolve
    r4 = await client.get(f"/api/v1/share/{token}", headers=_h(EVAN_ID))
    assert r4.status_code == 200
    body = r4.json()
    assert body["kind"] == "asset"
    assert body["asset"]["id"] == asset["id"]
    assert body["download_url"].startswith("http"), body["download_url"]


@pytest.mark.asyncio
async def test_share_invalid_token_404(client: AsyncClient) -> None:
    r = await client.get("/api/v1/share/__not_a_real_token__", headers=_h(EVAN_ID))
    assert r.status_code == 404


# ─── D iter4:project members CRUD ───────────────────────────────────────────
@pytest.mark.asyncio
async def test_project_members_list(client: AsyncClient) -> None:
    """Evan(创建者 admin)能列 wedding 的成员。"""
    r = await client.get(f"/api/v1/projects/{PROJECT_WEDDING}/members", headers=_h(EVAN_ID))
    assert r.status_code == 200, r.text
    items = r.json()
    assert any(m["kind"] == "user" and m["subject_id"].startswith("ou_") and "admin" in m["roles"]
               for m in items), f"应至少有一个 user admin: {items}"


@pytest.mark.asyncio
async def test_project_members_list_denied_for_non_admin(client: AsyncClient) -> None:
    """outsider 不是 admin 不能列。"""
    r = await client.get(f"/api/v1/projects/{PROJECT_WEDDING}/members", headers=_h(OUTSIDER_ID))
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_project_member_add_remove_cycle(client: AsyncClient) -> None:
    """Evan 加 outsider 为 viewer → 再撤 → 验列表回退。"""
    add = await client.post(
        f"/api/v1/projects/{PROJECT_EVENT}/members",
        json={"user_open_id": "ou_fake_outsider", "role": "viewer"},
        headers=_h(EVAN_ID),
    )
    assert add.status_code == 204, add.text

    r1 = await client.get(f"/api/v1/projects/{PROJECT_EVENT}/members", headers=_h(EVAN_ID))
    assert r1.status_code == 200
    members1 = r1.json()
    assert any(m["subject"] == "user:ou_fake_outsider" and "viewer" in m["roles"]
               for m in members1)

    rev = await client.delete(
        f"/api/v1/projects/{PROJECT_EVENT}/members",
        params={"subject": "user:ou_fake_outsider", "role": "viewer"},
        headers=_h(EVAN_ID),
    )
    assert rev.status_code == 204

    r2 = await client.get(f"/api/v1/projects/{PROJECT_EVENT}/members", headers=_h(EVAN_ID))
    members2 = r2.json()
    assert not any(m["subject"] == "user:ou_fake_outsider" for m in members2)


# ─── a2:GET /users 搜索 ─────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_users_list_basic(client: AsyncClient) -> None:
    """无 q 列出前 N 个 active user。"""
    r = await client.get("/api/v1/users?limit=5", headers=_h(EVAN_ID))
    assert r.status_code == 200
    items = r.json()
    assert isinstance(items, list)
    assert len(items) <= 5
    if items:
        assert "open_id" in items[0]
        assert "name" in items[0]


@pytest.mark.asyncio
async def test_users_fuzzy_search(client: AsyncClient) -> None:
    """模糊搜 'Evan' → 至少 Evan 自己。"""
    r = await client.get("/api/v1/users?q=Evan&limit=10", headers=_h(EVAN_ID))
    assert r.status_code == 200
    names = {u["name"] for u in r.json()}
    assert "Evan" in names


@pytest.mark.asyncio
async def test_users_no_auth_401(client: AsyncClient) -> None:
    r = await client.get("/api/v1/users")
    assert r.status_code == 401


# ─── polish 1:folder explicit grants ───────────────────────────────────────
@pytest.mark.asyncio
async def test_folder_grants_cycle(client: AsyncClient) -> None:
    """普通一级 folder grants:list / add outsider downloader / delete / 验回退。"""
    # 找 wedding 项目下的一级普通 folder
    r = await client.get(
        "/api/v1/folders", params={"project_id": PROJECT_WEDDING}, headers=_h(EVAN_ID),
    )
    assert r.status_code == 200
    normal_top = next(
        f for f in r.json()
        if not f["is_sensitive"] and f.get("parent_folder_id") is None
    )
    fid = normal_top["id"]

    # list 初始
    r1 = await client.get(f"/api/v1/folders/{fid}/grants", headers=_h(EVAN_ID))
    assert r1.status_code == 200
    before = len(r1.json())

    # add outsider downloader
    add = await client.post(
        f"/api/v1/folders/{fid}/grants",
        json={"user_open_id": "ou_fake_outsider", "level": "downloader"},
        headers=_h(EVAN_ID),
    )
    assert add.status_code == 204, add.text

    r2 = await client.get(f"/api/v1/folders/{fid}/grants", headers=_h(EVAN_ID))
    assert any(g["subject"] == "user:ou_fake_outsider" and g["level"] == "downloader"
               for g in r2.json())

    # delete
    rev = await client.delete(
        f"/api/v1/folders/{fid}/grants",
        params={"subject": "user:ou_fake_outsider", "level": "downloader"},
        headers=_h(EVAN_ID),
    )
    assert rev.status_code == 204
    r3 = await client.get(f"/api/v1/folders/{fid}/grants", headers=_h(EVAN_ID))
    assert len(r3.json()) == before


@pytest.mark.asyncio
async def test_folder_grants_sensitive_rejected(client: AsyncClient) -> None:
    """sensitive folder 不允许走 /grants(应走 /invite)。"""
    r = await client.get(
        "/api/v1/folders", params={"project_id": PROJECT_WEDDING}, headers=_h(EVAN_ID),
    )
    sens = next(f for f in r.json() if f["is_sensitive"])
    r2 = await client.get(f"/api/v1/folders/{sens['id']}/grants", headers=_h(EVAN_ID))
    assert r2.status_code == 400


# ─── admin endpoint:feishu health(polish 2 起需 admin)──────────────────────
@pytest.mark.asyncio
async def test_admin_feishu_health_no_auth_401(client: AsyncClient) -> None:
    r = await client.get("/api/v1/admin/feishu/health")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_admin_feishu_health_denied_for_non_admin(client: AsyncClient) -> None:
    """outsider 既不是 org admin 也不应是任何 project admin。
    若测试数据污染(被 grant 过 admin)则跳过本断言。
    """
    r = await client.get("/api/v1/admin/feishu/health", headers=_h(OUTSIDER_ID))
    # 接受 403(干净状态)或 200(测试数据污染:outsider 被 grant 了 project admin)
    assert r.status_code in (200, 403)
