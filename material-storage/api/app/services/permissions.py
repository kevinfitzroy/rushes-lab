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
    ClientTuple,
    ClientWriteRequest,
)
from openfga_sdk.models import RelationshipCondition

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
        parent_type: Literal["project", "folder"],
        parent_id: str,
    ) -> None:
        """新建 folder 写 parent tuple(model 简化 v2 后,统一 folder type)。"""
        await self._client.write(
            ClientWriteRequest(
                writes=[
                    ClientTuple(
                        user=f"{parent_type}:{parent_id}",
                        relation="parent",
                        object=f"folder:{folder_id}",
                    )
                ]
            )
        )

    async def bootstrap_asset(
        self,
        asset_id: str,
        parent_folder_id: str,
    ) -> None:
        """新建 asset 写 parent tuple(parent 永远是 folder)。"""
        await self._client.write(
            ClientWriteRequest(
                writes=[
                    ClientTuple(
                        user=f"folder:{parent_folder_id}",
                        relation="parent",
                        object=f"asset:{asset_id}",
                    )
                ]
            )
        )

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
