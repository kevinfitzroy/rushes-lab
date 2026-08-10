"""#151 标签 + 盲搜 — 集成测试(跑在 ms-api 容器内)。

预期前置(同 test_v4_permissions):
  1. seed_demo_data.py 已跑过(3 项目 / 40 folder / 真 user Evan / fake outsider)
  2. OpenFGA store / model 已 push
  3. env=dev(允许 X-User-Id header 模拟身份)

覆盖(issue #151 验收):
  - 硬验收:搜索结果按 can_view 过滤 —— sensitive 素材存在性零泄露(outsider 搜不到)
  - 打标 → 搜索 → 命中 e2e(user_labels / notes / filename 三路都验)
  - 打标权限:非 uploader 403;系统 admin 直通

review fix(#157 review,F1/F8):user_labels 模糊分支改为
`array_to_string(user_labels,' ') ILIKE`(不再 unnest → `lbl.unnest_1`
列名 PG 不认导致 500);本文件 e2e 用例即该路径的回归测试。
"""
from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.routers.assets import _escape_like, _normalize_labels


# ─── 纯函数单测(本机可跑,不依赖容器)────────────────────────────────────────
class TestLabelHelpers:
    def test_escape_like(self) -> None:
        assert _escape_like("a%b_c\\d") == "a\\%b\\_c\\\\d"
        assert _escape_like("plain") == "plain"

    def test_normalize_labels(self) -> None:
        assert _normalize_labels([" 婚礼 ", " 婚礼", "外景", "", "  "]) == ["婚礼", "外景"]
        assert _normalize_labels([]) == []
        long = "x" * 100
        out = _normalize_labels([long])
        assert len(out[0]) == 64  # 截断到列宽
        many = [f"l{i}" for i in range(100)]
        assert len(_normalize_labels(many)) == 50  # 上限 50

# seed 写死的真 user 和 fake outsider id(种子脚本里 hardcode,与 test_v4_permissions 一致)
EVAN_ID = "3f1b659e-9ef1-4e65-aa03-4407ad7bcfc4"
OUTSIDER_ID = "00000000-0000-0000-0000-0000000000aa"

PROJECT_WEDDING = "11111111-1111-1111-1111-111111111101"
PROJECT_EVENT = "11111111-1111-1111-1111-111111111103"

# seed 的 folder uuid 是确定性 uuid5(见 seed_demo_data._folder_uuid)
WEDDING_FOLDER_NAME = "现场原片"
WEDDING_SENSITIVE_NAME = "客户私密照(VIP)"


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


# ─── helper:在 seed 项目里挑 folder / 首个 asset ────────────────────────────
async def _folder_id(client: AsyncClient, project_id: str, name: str) -> str:
    r = await client.get("/api/v1/folders", params={"project_id": project_id}, headers=_h(EVAN_ID))
    assert r.status_code == 200, r.text
    folder = next(f for f in r.json() if f["name"] == name)
    return folder["id"]


async def _first_asset_id(client: AsyncClient, folder_id: str) -> str:
    r = await client.get("/api/v1/assets", params={"folder_id": folder_id}, headers=_h(EVAN_ID))
    assert r.status_code == 200, r.text
    assets = r.json()
    assert assets, f"folder {folder_id} 应至少 1 个 seed asset"
    return assets[0]["id"]


# ─── 打标 e2e(验收 3)────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_tag_then_search_hit_by_label(client: AsyncClient) -> None:
    """Evan 给一个普通 folder 的 asset 打标 → 搜该标签命中。"""
    fid = await _folder_id(client, PROJECT_WEDDING, WEDDING_FOLDER_NAME)
    aid = await _first_asset_id(client, fid)

    label = "婚礼外景"
    r = await client.patch(
        f"/api/v1/assets/{aid}/meta",
        json={"user_labels": [label, "  空标签  "], "notes": "给客户的初版"},
        headers=_h(EVAN_ID),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert label in body["user_labels"]
    assert "空标签" in body["user_labels"]  # trim 生效
    assert body["notes"] == "给客户的初版"

    # 按标签搜 → 命中
    r2 = await client.get("/api/v1/assets/search", params={"q": label}, headers=_h(EVAN_ID))
    assert r2.status_code == 200, r2.text
    results = r2.json()
    assert any(x["id"] == aid for x in results), f"搜 '{label}' 应命中 {aid}: {results}"

    # 返回结构带归属信息(前端导航用)
    hit = next(x for x in results if x["id"] == aid)
    assert hit["folder_name"] == WEDDING_FOLDER_NAME
    assert hit["project_id"] == PROJECT_WEDDING


@pytest.mark.asyncio
async def test_search_hit_by_notes_and_filename(client: AsyncClient) -> None:
    """备注 / 文件名两路也要能搜到(盲搜匹配范围 = filename + user_labels + notes)。"""
    fid = await _folder_id(client, PROJECT_WEDDING, WEDDING_FOLDER_NAME)
    aid = await _first_asset_id(client, fid)

    # notes 命中
    r = await client.patch(
        f"/api/v1/assets/{aid}/meta",
        json={"notes": "客户指定要无版税音乐"},
        headers=_h(EVAN_ID),
    )
    assert r.status_code == 200, r.text
    r2 = await client.get("/api/v1/assets/search", params={"q": "版税"}, headers=_h(EVAN_ID))
    assert r2.status_code == 200
    assert any(x["id"] == aid for x in r2.json())

    # filename 命中(seed 文件名 demo-01.txt,搜 "demo-0" 应命中)。
    # 69 个 asset 文件名都匹配 "demo-0",默认 limit=50 按 created_at DESC 截断,
    # aid(最早创建)排在第 69 名 → 必须显式 limit=200(端点上限)才能扫到
    r3 = await client.get(
        "/api/v1/assets/search",
        params={"q": "demo-0", "limit": 200}, headers=_h(EVAN_ID),
    )
    assert r3.status_code == 200
    assert any(x["id"] == aid for x in r3.json())


@pytest.mark.asyncio
async def test_tag_denied_for_outsider(client: AsyncClient) -> None:
    """outsider 无 can_upload → 打标 403(不写 user_labels)。"""
    fid = await _folder_id(client, PROJECT_EVENT, "现场视频")
    # outsider 对 public 项目无 uploader → 403
    r = await client.get("/api/v1/assets", params={"folder_id": fid}, headers=_h(EVAN_ID))
    aid = r.json()[0]["id"]
    r2 = await client.patch(
        f"/api/v1/assets/{aid}/meta",
        json={"user_labels": ["x"]},
        headers=_h(OUTSIDER_ID),
    )
    assert r2.status_code == 403, r2.text


# ─── 硬验收:sensitive 存在性零泄露(验收 1)───────────────────────────────────
@pytest.mark.asyncio
async def test_search_sensitive_zero_leak_for_outsider(client: AsyncClient) -> None:
    """outsider 对 sensitive 素材无任何 tuple:
    - 搜索其标签 → 零命中(名称/计数都不泄露)
    - 搜索其 notes 关键词 → 零命中
    - 搜索其 filename → 零命中
    """
    sfid = await _folder_id(client, PROJECT_WEDDING, WEDDING_SENSITIVE_NAME)
    r = await client.get("/api/v1/assets", params={"folder_id": sfid}, headers=_h(EVAN_ID))
    assert r.status_code == 200
    s_assets = r.json()
    assert s_assets, "seed sensitive folder 应至少 1 个 asset"
    s_aid = s_assets[0]["id"]
    s_filename = s_assets[0]["filename"]

    # Evan 打上"绝密标签"(sensitive 素材)
    r_tag = await client.patch(
        f"/api/v1/assets/{s_aid}/meta",
        json={"user_labels": ["绝密标签xyz"], "notes": "不可外泄"},
        headers=_h(EVAN_ID),
    )
    assert r_tag.status_code == 200, r_tag.text

    # outsider 搜 —— 三路都不该命中
    for q in ("绝密标签xyz", "不可外泄", s_filename[:6]):
        r2 = await client.get("/api/v1/assets/search", params={"q": q}, headers=_h(OUTSIDER_ID))
        assert r2.status_code == 200, r2.text
        results = r2.json()
        assert all(x["id"] != s_aid for x in results), \
            f"outsider 搜 '{q}' 泄露了 sensitive asset {s_aid}: {results}"

    # outsider 对 public 项目也搜不到(wedding 是 private 项目,整个不可见)
    r3 = await client.get(
        "/api/v1/assets/search", params={"q": "demo-0"}, headers=_h(OUTSIDER_ID),
    )
    assert r3.status_code == 200
    assert all(x["project_id"] != PROJECT_WEDDING for x in r3.json()), \
        f"outsider 不应见 private 项目 assets: {r3.json()}"


@pytest.mark.asyncio
async def test_search_evan_sees_sensitive(client: AsyncClient) -> None:
    """Evan 被 seed 邀请进 sensitive folder → 搜得到(对照上面 outsider 零泄露)。"""
    sfid = await _folder_id(client, PROJECT_WEDDING, WEDDING_SENSITIVE_NAME)
    r = await client.get("/api/v1/assets", params={"folder_id": sfid}, headers=_h(EVAN_ID))
    s_aid = r.json()[0]["id"]

    r2 = await client.get(
        "/api/v1/assets/search", params={"q": "demo-0"}, headers=_h(EVAN_ID),
    )
    assert r2.status_code == 200
    hits = [x for x in r2.json() if x["id"] == s_aid]
    assert hits, f"Evan 应能搜到自己的 sensitive asset: {r2.json()}"
    assert hits[0]["folder_name"] == WEDDING_SENSITIVE_NAME


# ─── 杂项 ────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_search_requires_auth(client: AsyncClient) -> None:
    r = await client.get("/api/v1/assets/search", params={"q": "x"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_search_empty_q_400(client: AsyncClient) -> None:
    r = await client.get("/api/v1/assets/search", params={"q": "   "}, headers=_h(EVAN_ID))
    assert r.status_code == 400, r.text


@pytest.mark.asyncio
async def test_meta_requires_auth(client: AsyncClient) -> None:
    fid = await _folder_id(client, PROJECT_WEDDING, WEDDING_FOLDER_NAME)
    aid = await _first_asset_id(client, fid)
    r = await client.patch(f"/api/v1/assets/{aid}/meta", json={"user_labels": ["x"]})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_meta_missing_asset_404(client: AsyncClient) -> None:
    r = await client.patch(
        f"/api/v1/assets/{uuid.uuid4()}/meta", json={"user_labels": ["x"]},
        headers=_h(EVAN_ID),
    )
    assert r.status_code == 404, r.text
