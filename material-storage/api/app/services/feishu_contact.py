"""飞书通讯录 v3 API 客户端 — a2 iter:同步 user/dept/group 进 OpenFGA。

复用 FeishuClient 的 tenant_access_token + httpx;只读 API:
  - GET /open-apis/contact/v3/scopes                              — app 可见范围(顶级部门 ids)
  - GET /open-apis/contact/v3/departments/{id}/children           — 子部门(分页)
  - GET /open-apis/contact/v3/departments/{id}                    — 部门详情(parent_department_id)
  - GET /open-apis/contact/v3/users/find_by_department            — 部门下 user(分页)
  - GET /open-apis/contact/v3/users/{open_id}                     — user 详情(department_ids)
  - GET /open-apis/contact/v3/group/simplelist                    — 用户组列表(分页)
  - GET /open-apis/contact/v3/group/{group_id}/member/simplelist  — 组成员

权限 scope(飞书后台需勾):
  contact:contact.base:readonly + contact:contact.employee_id:readonly +
  contact:department.base:readonly + contact:user.base:readonly + contact:group:readonly

注意:飞书 OpenAPI 受 "通讯录授权范围" 限制 — app 在后台只能看 admin 配的部门;
PoC 简化为 app 全公司可见(管理员后台配)。
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from app.services.feishu_client import FeishuAPIError, FeishuClient

log = logging.getLogger(__name__)


class FeishuContactClient:
    def __init__(self, feishu: FeishuClient):
        self._f = feishu

    # ─── scopes ──────────────────────────────────────────────────────────────
    async def get_scopes(self) -> dict[str, list[str]]:
        """app 可见的顶级部门 + 顶级 user。

        返:{"department_ids": [...], "user_ids": [...], "group_ids": [...]}
        ids 均为 open_id 类型。
        """
        data = await self._get("/open-apis/contact/v3/scopes", params={
            "user_id_type": "open_id",
            "department_id_type": "open_department_id",
        })
        return {
            "department_ids": data.get("department_ids", []),
            "user_ids": data.get("user_ids", []),
            "group_ids": data.get("group_ids", []),
        }

    # ─── department ──────────────────────────────────────────────────────────
    async def list_child_departments(self, department_id: str) -> AsyncIterator[dict[str, Any]]:
        """直接子部门(分页 yield)。

        item 关键字段:open_department_id / name / parent_department_id /
        member_count / leader_user_id / order
        """
        async for item in self._paginate(
            f"/open-apis/contact/v3/departments/{department_id}/children",
            params={
                "department_id_type": "open_department_id",
                "user_id_type": "open_id",
                "fetch_child": "false",  # 只直接子,自己递归
                "page_size": 50,
            },
        ):
            yield item

    async def get_department(self, department_id: str) -> dict[str, Any] | None:
        try:
            data = await self._get(
                f"/open-apis/contact/v3/departments/{department_id}",
                params={"department_id_type": "open_department_id"},
            )
            return data.get("department")
        except FeishuAPIError as e:
            if e.code in (404, 230402):
                return None
            raise

    # ─── user ────────────────────────────────────────────────────────────────
    async def list_users_in_department(
        self, department_id: str
    ) -> AsyncIterator[dict[str, Any]]:
        """部门下直接 user(分页)。

        item 字段:open_id / union_id / name / email / mobile / department_ids[] /
        status.is_activated / status.is_resigned
        """
        async for item in self._paginate(
            "/open-apis/contact/v3/users/find_by_department",
            params={
                "department_id": department_id,
                "department_id_type": "open_department_id",
                "user_id_type": "open_id",
                "page_size": 50,
            },
        ):
            yield item

    async def get_user(self, open_id: str) -> dict[str, Any] | None:
        try:
            data = await self._get(
                f"/open-apis/contact/v3/users/{open_id}",
                params={
                    "user_id_type": "open_id",
                    "department_id_type": "open_department_id",
                },
            )
            return data.get("user")
        except FeishuAPIError as e:
            if e.code in (404, 99991668):
                return None
            raise

    # ─── group ───────────────────────────────────────────────────────────────
    async def list_groups(self) -> AsyncIterator[dict[str, Any]]:
        """全部用户组(分页)。item 字段:id / name / member_user_count / description"""
        async for item in self._paginate(
            "/open-apis/contact/v3/group/simplelist",
            params={"page_size": 50},
            list_key="grouplist",
        ):
            yield item

    async def list_group_members(self, group_id: str) -> AsyncIterator[dict[str, Any]]:
        """组成员(分页)。item 字段:member_id(open_id)/ member_type / member_id_type"""
        async for item in self._paginate(
            f"/open-apis/contact/v3/group/{group_id}/member/simplelist",
            params={
                "member_id_type": "open_id",
                "member_type": "user",     # 仅 user;departments 单独处理
                "page_size": 50,
            },
            list_key="memberlist",
        ):
            yield item

    # ─── internals ───────────────────────────────────────────────────────────
    async def _get(self, path: str, *, params: dict[str, Any]) -> dict[str, Any]:
        token = await self._f.get_tenant_access_token()
        resp = await self._f._http.get(  # type: ignore[attr-defined]
            path, params=params, headers={"Authorization": f"Bearer {token}"},
        )
        return self._f._raise_or_data(resp)  # type: ignore[attr-defined]

    async def _paginate(
        self, path: str, *, params: dict[str, Any], list_key: str = "items",
    ) -> AsyncIterator[dict[str, Any]]:
        page_token: str | None = None
        while True:
            p = dict(params)
            if page_token:
                p["page_token"] = page_token
            try:
                data = await self._get(path, params=p)
            except FeishuAPIError as e:
                # 99991663 = 权限不够;99991668 = 资源不存在
                log.warning("feishu paginate %s code=%s msg=%s", path, e.code, e.msg)
                return
            items = data.get(list_key) or data.get("items") or []
            for it in items:
                yield it
            page_token = data.get("page_token")
            if not data.get("has_more") or not page_token:
                return
