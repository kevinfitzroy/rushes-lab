"""OpenFGA SDK wrapper — Phase B-2。

封装业务粗粒度权限:
  - grant_sensitive_access:审批通过后写 conditional tuple(time-limited)
  - revoke_sensitive_access:删 tuple
  - check:每次访问 check
  - revoke_user_completely:离职闭环,删 user 所有 tuple
  - bootstrap_project / bootstrap_folder / bootstrap_asset:create 时写 hierarchy

参 PoC openfga model:material-storage/poc/openfga/store.fga.yaml
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Literal

from openfga_sdk import OpenFgaClient
from openfga_sdk.client.configuration import ClientConfiguration
from openfga_sdk.client.models import (
    ClientCheckRequest,
    ClientListObjectsRequest,
    ClientTuple,
    ClientWriteRequest,
)
from openfga_sdk.client.models.list_users_request import ClientListUsersRequest
from openfga_sdk.models import FgaObject, RelationshipCondition
from openfga_sdk.models.user_type_filter import UserTypeFilter

from app.settings import Settings

log = logging.getLogger(__name__)


Relation = Literal[
    "admin",
    "editor",
    "viewer",
    "member",
    "explicit_viewer",
    "can_view",
    "can_download",
    "can_edit",
    "can_delete",
]


class PermissionsService:
    def __init__(self, settings: Settings):
        self._settings = settings
        config = ClientConfiguration(
            api_url=settings.openfga_api_url,
            store_id=settings.openfga_store_id,
            authorization_model_id=settings.openfga_model_id,
        )
        self._client = OpenFgaClient(config)

    async def close(self) -> None:
        await self._client.close()

    # ─── check ───────────────────────────────────────────────────────────────
    async def check(
        self,
        user_id: str,
        relation: Relation,
        object_type: str,
        object_id: str,
        *,
        current_time: datetime | None = None,
    ) -> bool:
        ctx = {"current_time": (current_time or datetime.now(timezone.utc)).isoformat()}
        resp = await self._client.check(
            ClientCheckRequest(
                user=f"user:{user_id}",
                relation=relation,
                object=f"{object_type}:{object_id}",
                context=ctx,
            )
        )
        return resp.allowed

    # ─── list_objects:取 user 可访问的 object IDs(给业务 list filter 用)────
    async def list_objects(
        self,
        user_id: str,
        relation: Relation,
        object_type: str,
        *,
        current_time: datetime | None = None,
    ) -> list[str]:
        """返回 type 类型下,user 拥有指定 relation 的所有 object ID 列表。

        典型用法:list_projects 时调 `list_objects(user, "can_view", "project")`,
        union 上 `project.visibility=public` 得到最终可见列表。
        """
        ctx = {"current_time": (current_time or datetime.now(timezone.utc)).isoformat()}
        resp = await self._client.list_objects(
            ClientListObjectsRequest(
                user=f"user:{user_id}",
                relation=relation,
                type=object_type,
                context=ctx,
            )
        )
        # OpenFGA 返回 ["project:abc-123", "project:def-456"];strip type prefix
        prefix = f"{object_type}:"
        return [obj.removeprefix(prefix) for obj in resp.objects if obj.startswith(prefix)]

    # ─── list_users:取对某 object 拥有指定 relation 的 user 列表 ────────────
    async def list_users_with_relation(
        self,
        object_type: str,
        object_id: str,
        relation: Relation,
        *,
        current_time: datetime | None = None,
    ) -> list[str]:
        """返回 type=user 的 internal user_id 列表(stripped prefix)。

        典型用法:approval 推卡片 → 找 target 的 admin → 反查 feishu_open_id 推送。
        """
        ctx = {"current_time": (current_time or datetime.now(timezone.utc)).isoformat()}
        resp = await self._client.list_users(
            ClientListUsersRequest(
                object=FgaObject(type=object_type, id=object_id),
                relation=relation,
                user_filters=[UserTypeFilter(type="user")],
                context=ctx,
            )
        )
        out: list[str] = []
        for u in resp.users:
            obj = getattr(u, "object", None)
            if obj is None:
                continue
            uid = getattr(obj, "id", None)
            if uid:
                out.append(uid)
        return out

    # ─── grant 临时下载(model 简化 v2 后,通用 project / asset 级)──────────
    async def grant_explicit_download(
        self,
        user_id: str,
        object_type: Literal["project", "asset"],
        object_id: str,
        duration_seconds: int,
    ) -> None:
        """审批通过后写 time-limited download grant;过期自动失效(无 cron)。

        object_type:
          - "project" → 批量下载整个 project(如实习生 30d / 一次性批量审批)
          - "asset"   → 单文件下载(细粒度,每次审批一个)
        """
        grant_time = datetime.now(timezone.utc).isoformat()
        await self._client.write(
            ClientWriteRequest(
                writes=[
                    ClientTuple(
                        user=f"user:{user_id}",
                        relation="explicit_downloader",
                        object=f"{object_type}:{object_id}",
                        condition=RelationshipCondition(
                            name="non_expired_grant",
                            context={
                                "grant_time": grant_time,
                                "grant_duration": f"{duration_seconds}s",
                            },
                        ),
                    )
                ]
            )
        )
        log.info("granted explicit_download user=%s %s=%s ttl=%ds",
                 user_id, object_type, object_id, duration_seconds)

    async def revoke_explicit_download(
        self,
        user_id: str,
        object_type: Literal["project", "asset"],
        object_id: str,
    ) -> None:
        await self._client.write(
            ClientWriteRequest(
                deletes=[
                    ClientTuple(
                        user=f"user:{user_id}",
                        relation="explicit_downloader",
                        object=f"{object_type}:{object_id}",
                    )
                ]
            )
        )
        log.info("revoked explicit_download user=%s %s=%s", user_id, object_type, object_id)

    # ─── 离职闭环 ────────────────────────────────────────────────────────────
    async def revoke_user_completely(self, user_id: str) -> int:
        """飞书 contact.user.deleted_v3 触发,删该 user 所有 tuple。"""
        from openfga_sdk.models import TupleKey
        resp = await self._client.read(TupleKey(user=f"user:{user_id}"))
        if not resp.tuples:
            return 0

        deletes = [
            ClientTuple(user=t.key.user, relation=t.key.relation, object=t.key.object)
            for t in resp.tuples
        ]
        BATCH = 50
        total = 0
        for i in range(0, len(deletes), BATCH):
            await self._client.write(ClientWriteRequest(deletes=deletes[i : i + BATCH]))
            total += len(deletes[i : i + BATCH])
        log.info("revoke_user_completely user=%s deleted=%d", user_id, total)
        return total

    # ─── bootstrap hierarchy ──────────────────────────────────────────────────
    async def bootstrap_project(self, project_id: str, organization_id: str) -> None:
        await self._client.write(
            ClientWriteRequest(
                writes=[
                    ClientTuple(
                        user=f"organization:{organization_id}",
                        relation="organization",
                        object=f"project:{project_id}",
                    )
                ]
            )
        )

    async def bootstrap_folder(
        self,
        folder_id: str,
        parent_type: Literal["project", "folder", "sensitive_folder"],
        parent_id: str,
        is_sensitive: bool,
    ) -> None:
        """新建 folder 写 parent tuple(model v3:sensitive_folder 邀请制 type 重新引入)。

        is_sensitive=True:folder 用 sensitive_folder type,默认 project member 看不到;
                          必须 admin 显式 invite_to_sensitive_folder
        is_sensitive=False:普通 folder,project member 自动可见
        """
        folder_type = "sensitive_folder" if is_sensitive else "folder"
        await self._client.write(
            ClientWriteRequest(
                writes=[
                    ClientTuple(
                        user=f"{parent_type}:{parent_id}",
                        relation="parent",
                        object=f"{folder_type}:{folder_id}",
                    )
                ]
            )
        )

    async def bootstrap_asset(
        self,
        asset_id: str,
        parent_folder_id: str,
        parent_is_sensitive: bool,
    ) -> None:
        """新建 asset 写 parent tuple(parent 按 folder.is_sensitive 决定 type)。"""
        parent_type = "sensitive_folder" if parent_is_sensitive else "folder"
        await self._client.write(
            ClientWriteRequest(
                writes=[
                    ClientTuple(
                        user=f"{parent_type}:{parent_folder_id}",
                        relation="parent",
                        object=f"asset:{asset_id}",
                    )
                ]
            )
        )

    # ─── sensitive_folder 邀请制(v3 新加)───────────────────────────────────
    async def invite_to_sensitive_folder(
        self,
        sensitive_folder_id: str,
        *,
        user_id: str | None = None,
        group_id: str | None = None,
        duration_seconds: int | None = None,
    ) -> None:
        """邀请 user / group 进入 sensitive_folder 可见名单。

        - duration_seconds=None  → 永久邀请(invited relation,无 condition)
        - duration_seconds=int   → 时间限定邀请(explicit_invited relation + non_expired_grant)
                                   过期自动失效

        二选一:user_id 或 group_id(group#member 形式)。
        """
        if (user_id is None) == (group_id is None):
            raise ValueError("must specify exactly one of user_id / group_id")

        subject = f"user:{user_id}" if user_id else f"group:{group_id}#member"

        if duration_seconds is None:
            # 永久邀请 - invited relation
            await self._client.write(
                ClientWriteRequest(
                    writes=[
                        ClientTuple(
                            user=subject,
                            relation="invited",
                            object=f"sensitive_folder:{sensitive_folder_id}",
                        )
                    ]
                )
            )
            log.info("permanent invite to sensitive_folder subject=%s folder=%s",
                     subject, sensitive_folder_id)
        else:
            # 临时邀请 - explicit_invited + condition
            grant_time = datetime.now(timezone.utc).isoformat()
            await self._client.write(
                ClientWriteRequest(
                    writes=[
                        ClientTuple(
                            user=subject,
                            relation="explicit_invited",
                            object=f"sensitive_folder:{sensitive_folder_id}",
                            condition=RelationshipCondition(
                                name="non_expired_grant",
                                context={
                                    "grant_time": grant_time,
                                    "grant_duration": f"{duration_seconds}s",
                                },
                            ),
                        )
                    ]
                )
            )
            log.info("temporary invite to sensitive_folder subject=%s folder=%s ttl=%ds",
                     subject, sensitive_folder_id, duration_seconds)

    async def revoke_from_sensitive_folder(
        self,
        sensitive_folder_id: str,
        *,
        user_id: str | None = None,
        group_id: str | None = None,
        permanent: bool = True,
    ) -> None:
        """撤销 sensitive_folder 邀请。

        permanent=True → 删 invited(永久)tuple
        permanent=False → 删 explicit_invited(临时)tuple
        """
        if (user_id is None) == (group_id is None):
            raise ValueError("must specify exactly one of user_id / group_id")

        subject = f"user:{user_id}" if user_id else f"group:{group_id}#member"
        relation = "invited" if permanent else "explicit_invited"

        await self._client.write(
            ClientWriteRequest(
                deletes=[
                    ClientTuple(
                        user=subject,
                        relation=relation,
                        object=f"sensitive_folder:{sensitive_folder_id}",
                    )
                ]
            )
        )
        log.info("revoked %s invite subject=%s folder=%s",
                 "permanent" if permanent else "temporary", subject, sensitive_folder_id)

    # ─── group / org membership ──────────────────────────────────────────────
    async def add_user_to_group(self, user_id: str, group_id: str) -> None:
        await self._client.write(
            ClientWriteRequest(
                writes=[
                    ClientTuple(
                        user=f"user:{user_id}",
                        relation="member",
                        object=f"group:{group_id}",
                    )
                ]
            )
        )

    async def assign_group_to_project(
        self, group_id: str, project_id: str, role: Literal["admin", "editor", "viewer"]
    ) -> None:
        await self._client.write(
            ClientWriteRequest(
                writes=[
                    ClientTuple(
                        user=f"group:{group_id}#member",
                        relation=role,
                        object=f"project:{project_id}",
                    )
                ]
            )
        )

    async def assign_user_to_organization(
        self, user_id: str, organization_id: str, role: Literal["admin", "member"]
    ) -> None:
        await self._client.write(
            ClientWriteRequest(
                writes=[
                    ClientTuple(
                        user=f"user:{user_id}",
                        relation=role,
                        object=f"organization:{organization_id}",
                    )
                ]
            )
        )


async def create_permissions_service(settings: Settings) -> PermissionsService:
    svc = PermissionsService(settings)
    try:
        await svc._client.read_authorization_models()
    except Exception as e:
        log.warning("OpenFGA init check failed: %s", e)
    return svc
