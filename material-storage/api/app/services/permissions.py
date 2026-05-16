"""OpenFGA SDK wrapper — iter a1 重构 (v4 model)。

变化(v3 → v4):
- subject 全用飞书 ID:user:<open_id> / group:<group_id> / department:<dept_id>
  / organization:<tenant_key>
- 低层接口接 raw subject string("user:ou_xxx"),允许 user / group#member / department#member 等任意主体
- 高层 helpers:bootstrap_* + add/remove_project_subject + grant_folder_explicit_subject +
  invite_sensitive_folder + grant_explicit_download(asset 级临时下载)

参 v4 model:material-storage/poc/openfga/store.fga.yaml
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


# project 三轴 + admin
ProjectRole = Literal["admin", "viewer", "downloader", "uploader"]
# folder 子级 explicit grant 三种(business 层 enforce 仅 level-1 folder)
FolderExplicit = Literal["explicit_viewer", "explicit_downloader", "explicit_uploader"]
# sensitive folder 邀请两级
SensitiveInviteLevel = Literal["viewer", "downloader"]


def fmt_subject(kind: Literal["user", "group", "department", "organization"], id_: str) -> str:
    """通用 subject 字符串(group / department 自动加 #member 后缀,user / organization 不加)。"""
    if kind in ("group", "department"):
        return f"{kind}:{id_}#member"
    return f"{kind}:{id_}"


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

    # ───────────────────────── 低层 check / list ──────────────────────────────
    async def check(
        self,
        *,
        user_subject: str,                       # e.g. "user:ou_xxx" 或 "group:gid#member"
        relation: str,
        object_type: str,
        object_id: str,
        current_time: datetime | None = None,
    ) -> bool:
        ctx = {"current_time": (current_time or datetime.now(timezone.utc)).isoformat()}
        resp = await self._client.check(
            ClientCheckRequest(
                user=user_subject,
                relation=relation,
                object=f"{object_type}:{object_id}",
                context=ctx,
            )
        )
        return resp.allowed

    async def list_objects(
        self,
        *,
        user_subject: str,
        relation: str,
        object_type: str,
        current_time: datetime | None = None,
    ) -> list[str]:
        """user 可达的 type=object_type 的 ID 列表(stripped prefix)。"""
        ctx = {"current_time": (current_time or datetime.now(timezone.utc)).isoformat()}
        resp = await self._client.list_objects(
            ClientListObjectsRequest(
                user=user_subject,
                relation=relation,
                type=object_type,
                context=ctx,
            )
        )
        prefix = f"{object_type}:"
        return [obj.removeprefix(prefix) for obj in resp.objects if obj.startswith(prefix)]

    async def list_users_with_relation(
        self,
        *,
        object_type: str,
        object_id: str,
        relation: str,
        current_time: datetime | None = None,
    ) -> list[str]:
        """对某 object 拥有指定 relation 的 type=user 的 ID 列表(飞书 open_id)。"""
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
            uid = getattr(obj, "id", None) if obj else None
            if uid:
                out.append(uid)
        return out

    # ───────────────────────── bootstrap ──────────────────────────────────────
    async def bootstrap_project(
        self, *, project_id: str, organization_tenant_key: str, creator_open_id: str
    ) -> None:
        """create_project 后调用:写 project→org 关系 + 创建者 admin。"""
        await self._client.write(
            ClientWriteRequest(
                writes=[
                    ClientTuple(
                        user=f"organization:{organization_tenant_key}",
                        relation="org",
                        object=f"project:{project_id}",
                    ),
                    ClientTuple(
                        user=f"user:{creator_open_id}",
                        relation="admin",
                        object=f"project:{project_id}",
                    ),
                ]
            )
        )

    async def bootstrap_folder(
        self, *, folder_id: str, parent_type: Literal["project", "folder"], parent_id: str
    ) -> None:
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

    async def bootstrap_sensitive_folder(
        self, *, folder_id: str, project_id: str
    ) -> None:
        """sensitive folder 限挂 project(model v4 已 enforce)。"""
        await self._client.write(
            ClientWriteRequest(
                writes=[
                    ClientTuple(
                        user=f"project:{project_id}",
                        relation="parent",
                        object=f"sensitive_folder:{folder_id}",
                    )
                ]
            )
        )

    async def bootstrap_asset(
        self,
        *,
        asset_id: str,
        parent_type: Literal["folder", "sensitive_folder"],
        parent_id: str,
    ) -> None:
        await self._client.write(
            ClientWriteRequest(
                writes=[
                    ClientTuple(
                        user=f"{parent_type}:{parent_id}",
                        relation="parent",
                        object=f"asset:{asset_id}",
                    )
                ]
            )
        )

    # ───────────────────────── project subject 管理 ───────────────────────────
    async def add_project_subject(
        self, *, project_id: str, subject: str, role: ProjectRole
    ) -> None:
        """加 project 级 subject(viewer/downloader/uploader/admin)。

        subject 通常通过 fmt_subject() 构造,例如:
          add_project_subject(pid, fmt_subject('department', dept_id), 'viewer')
          add_project_subject(pid, fmt_subject('group', grp_id), 'downloader')
          add_project_subject(pid, fmt_subject('user', open_id), 'admin')
        """
        await self._client.write(
            ClientWriteRequest(
                writes=[
                    ClientTuple(user=subject, relation=role, object=f"project:{project_id}")
                ]
            )
        )

    async def remove_project_subject(
        self, *, project_id: str, subject: str, role: ProjectRole
    ) -> None:
        await self._client.write(
            ClientWriteRequest(
                deletes=[
                    ClientTuple(user=subject, relation=role, object=f"project:{project_id}")
                ]
            )
        )

    # ───────────────────────── folder explicit grant(仅一级)─────────────────
    async def grant_folder_explicit_subject(
        self, *, folder_id: str, subject: str, kind: FolderExplicit
    ) -> None:
        await self._client.write(
            ClientWriteRequest(
                writes=[
                    ClientTuple(user=subject, relation=kind, object=f"folder:{folder_id}")
                ]
            )
        )

    async def revoke_folder_explicit_subject(
        self, *, folder_id: str, subject: str, kind: FolderExplicit
    ) -> None:
        await self._client.write(
            ClientWriteRequest(
                deletes=[
                    ClientTuple(user=subject, relation=kind, object=f"folder:{folder_id}")
                ]
            )
        )

    # ───────────────────────── sensitive folder 邀请 ──────────────────────────
    async def invite_to_sensitive_folder(
        self,
        *,
        sensitive_folder_id: str,
        subject: str,                            # user / group#member / department#member
        level: SensitiveInviteLevel,             # viewer / downloader
        duration_seconds: int | None = None,    # None = 永久;int = 时间限定
    ) -> None:
        permanent = duration_seconds is None
        relation = (
            ("invited_" if permanent else "explicit_invited_") + level
        )
        if permanent:
            tup = ClientTuple(
                user=subject, relation=relation,
                object=f"sensitive_folder:{sensitive_folder_id}",
            )
        else:
            grant_time = datetime.now(timezone.utc).isoformat()
            tup = ClientTuple(
                user=subject, relation=relation,
                object=f"sensitive_folder:{sensitive_folder_id}",
                condition=RelationshipCondition(
                    name="non_expired_grant",
                    context={
                        "grant_time": grant_time,
                        "grant_duration": f"{duration_seconds}s",
                    },
                ),
            )
        await self._client.write(ClientWriteRequest(writes=[tup]))
        log.info("invite sensitive_folder=%s subject=%s level=%s ttl=%s",
                 sensitive_folder_id, subject, level,
                 f"{duration_seconds}s" if duration_seconds else "permanent")

    async def revoke_sensitive_folder_invite(
        self,
        *,
        sensitive_folder_id: str,
        subject: str,
        level: SensitiveInviteLevel,
        permanent: bool,
    ) -> None:
        relation = ("invited_" if permanent else "explicit_invited_") + level
        await self._client.write(
            ClientWriteRequest(
                deletes=[
                    ClientTuple(
                        user=subject, relation=relation,
                        object=f"sensitive_folder:{sensitive_folder_id}",
                    )
                ]
            )
        )

    # ───────────────────────── 离职闭环 ────────────────────────────────────────
    async def revoke_user_completely(self, user_open_id: str) -> int:
        """删某 user 所有 tuple(飞书离职事件触发)。"""
        from openfga_sdk.models import TupleKey
        resp = await self._client.read(TupleKey(user=f"user:{user_open_id}"))
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
        log.info("revoke_user_completely user=%s deleted=%d", user_open_id, total)
        return total

    # ───────────────────────── organization / department 同步 ─────────────────
    async def add_user_to_organization(
        self, *, organization_tenant_key: str, user_open_id: str
    ) -> None:
        """user OIDC 登录 / contact.user.created 时,加入 org member。"""
        await self._client.write(
            ClientWriteRequest(
                writes=[
                    ClientTuple(
                        user=f"user:{user_open_id}",
                        relation="member",
                        object=f"organization:{organization_tenant_key}",
                    )
                ]
            )
        )

    async def add_user_to_department(self, *, department_id: str, user_open_id: str) -> None:
        await self._client.write(
            ClientWriteRequest(
                writes=[
                    ClientTuple(
                        user=f"user:{user_open_id}",
                        relation="member",
                        object=f"department:{department_id}",
                    )
                ]
            )
        )

    async def remove_user_from_department(self, *, department_id: str, user_open_id: str) -> None:
        await self._client.write(
            ClientWriteRequest(
                deletes=[
                    ClientTuple(
                        user=f"user:{user_open_id}",
                        relation="member",
                        object=f"department:{department_id}",
                    )
                ]
            )
        )

    async def add_department_as_subdept(
        self, *, parent_department_id: str, child_department_id: str
    ) -> None:
        """嵌套部门:子部门 member 自动算父部门 member。"""
        await self._client.write(
            ClientWriteRequest(
                writes=[
                    ClientTuple(
                        user=f"department:{child_department_id}#member",
                        relation="member",
                        object=f"department:{parent_department_id}",
                    )
                ]
            )
        )

    async def add_user_to_group(self, *, group_id: str, user_open_id: str) -> None:
        await self._client.write(
            ClientWriteRequest(
                writes=[
                    ClientTuple(
                        user=f"user:{user_open_id}",
                        relation="member",
                        object=f"group:{group_id}",
                    )
                ]
            )
        )

    # ───────────────────────── 时间限定下载 grant(approval download)─────────
    async def grant_explicit_download(
        self,
        *,
        user_open_id: str,
        object_type: Literal["project", "asset"],
        object_id: str,
        duration_seconds: int,
    ) -> None:
        """审批通过的临时下载 grant — project 级(批量)或 asset 级(单文件)。

        到期自动失效(non_expired_grant condition,无需 cron 清理)。
        """
        grant_time = datetime.now(timezone.utc).isoformat()
        await self._client.write(
            ClientWriteRequest(
                writes=[
                    ClientTuple(
                        user=f"user:{user_open_id}",
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
        log.info("grant explicit_download user=%s %s=%s ttl=%ds",
                 user_open_id, object_type, object_id, duration_seconds)

    async def revoke_explicit_download(
        self,
        *,
        user_open_id: str,
        object_type: Literal["project", "asset"],
        object_id: str,
    ) -> None:
        await self._client.write(
            ClientWriteRequest(
                deletes=[
                    ClientTuple(
                        user=f"user:{user_open_id}",
                        relation="explicit_downloader",
                        object=f"{object_type}:{object_id}",
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
