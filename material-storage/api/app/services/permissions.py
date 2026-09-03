"""OpenFGA SDK wrapper — iter a1 重构 (v4 model);#148 subject 切本地 UUID。

subject 约定(#148 / ADR-0007 起):
- user:<users.id UUID>            — 本地用户(不再用飞书 open_id)
- group:<本地 groups.id UUID>#member — 本地用户组(groups 表,#148 新建)
- organization:<tenant_key>        — 组织(不变)

#154:department 轴写入已下线(ADR-0007),只保留读路径
(存量 department tuples 原样保留;USER_DIRECT_RELATIONS 里 ("department","member")
用于 revoke_user_completely 兜底清理)。

低层接口接 raw subject string("user:<uuid>"),允许 user / group#member 等任意主体。
高层 helpers:bootstrap_* + add/remove_project_subject + grant_folder_explicit_subject +
invite_sensitive_folder + grant_explicit_download(asset 级临时下载)。

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

# user 可作直接 subject 的 (type, relation) 全集(model v4 + #150 group)。
# revoke_user_completely 靠它枚举删干净;conditional tuple 无 context 时
# list_objects 不返回(自动过期),符合"撤权限"语义。
USER_DIRECT_RELATIONS: tuple[tuple[str, str], ...] = (
    ("organization", "admin"),
    ("organization", "member"),
    ("department", "member"),
    ("group", "member"),
    ("project", "admin"),
    ("project", "viewer"),
    ("project", "downloader"),
    ("project", "uploader"),
    ("project", "explicit_downloader"),
    ("folder", "explicit_viewer"),
    ("folder", "explicit_downloader"),
    ("folder", "explicit_uploader"),
    ("sensitive_folder", "invited_viewer"),
    ("sensitive_folder", "invited_downloader"),
    ("sensitive_folder", "explicit_invited_viewer"),
    ("sensitive_folder", "explicit_invited_downloader"),
    ("asset", "explicit_downloader"),
)


# project 三轴 + admin
ProjectRole = Literal["admin", "viewer", "downloader", "uploader"]
# folder 子级 explicit grant 三种(business 层 enforce 仅 level-1 folder)
FolderExplicit = Literal["explicit_viewer", "explicit_downloader", "explicit_uploader"]
# sensitive folder 邀请两级
SensitiveInviteLevel = Literal["viewer", "downloader"]


def fmt_subject(kind: Literal["user", "group"], id_: str) -> str:
    """通用 subject 字符串(group 自动加 #member 后缀,user 不加;#154:department 下线)。"""
    if kind == "group":
        return f"{kind}:{id_}#member"
    return f"{kind}:{id_}"


def is_already_exists_error(e: BaseException) -> bool:
    """判定 OpenFGA 写异常是否为「重复 tuple」。

    不匹配完整报错文案:openfga 镜像未固定版本,400 文案同时含 "already exists"
    与 "already existed" 且随版本可能漂移(PR #176 review P1-1)。
    改为 SDK 异常类型(400 ValidationException)+ 两者稳定公共子串 "already exist";
    非 400 类(网络 / 5xx)不视作重复,继续上抛。
    """
    from openfga_sdk.exceptions import ValidationException

    return isinstance(e, ValidationException) and "already exist" in str(e).lower()


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
        user_subject: str,                       # e.g. "user:<users.id UUID>" 或 "group:<gid>#member"
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
        """对某 object 拥有指定 relation 的 type=user 的 ID 列表(users.id UUID 字符串)。"""
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
        self, *, project_id: str, organization_tenant_key: str, creator_user_id: str
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
                        user=f"user:{creator_user_id}",
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
          add_project_subject(pid, fmt_subject('group', grp_id), 'downloader')
          add_project_subject(pid, fmt_subject('user', user_id), 'admin')
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
    # #129:folder.explicit_* 加 non_expired_grant condition;
    # duration_seconds=None → 100 年 grant_duration("视为永久"),保持 FolderGrantsPanel 语义
    _PERMANENT_GRANT_SECONDS = 100 * 365 * 24 * 3600  # 100 年

    async def grant_folder_explicit_subject(
        self, *, folder_id: str, subject: str, kind: FolderExplicit,
        duration_seconds: int | None = None,
    ) -> None:
        seconds = duration_seconds if duration_seconds is not None else self._PERMANENT_GRANT_SECONDS
        grant_time = datetime.now(timezone.utc).isoformat()
        tup = ClientTuple(
            user=subject, relation=kind, object=f"folder:{folder_id}",
            condition=RelationshipCondition(
                name="non_expired_grant",
                context={"grant_time": grant_time, "grant_duration": f"{seconds}s"},
            ),
        )
        try:
            await self._client.write(ClientWriteRequest(writes=[tup]))
        except Exception as e:
            # 'tuple already existed' → 先删后写(刷新 condition.grant_time)
            if is_already_exists_error(e):
                try:
                    await self._client.write(ClientWriteRequest(deletes=[
                        ClientTuple(user=subject, relation=kind, object=f"folder:{folder_id}")
                    ]))
                except Exception:  # noqa: BLE001
                    pass
                await self._client.write(ClientWriteRequest(writes=[tup]))
            else:
                raise

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
        subject: str,                            # user / group#member
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
    async def revoke_user_completely(self, user_id: str) -> int:
        """删某 user 所有 tuple(离职 / 禁用触发)。

        OpenFGA read 不支持纯 user 过滤(必须带 object),故按
        USER_DIRECT_RELATIONS 逐 (type, relation) list_objects 找候选对象,
        再全键 read 验证后批量删除 —— 避免把 group#member 派生来的对象也误删。
        """
        from openfga_sdk.models import ReadRequestTupleKey
        deletes: list[ClientTuple] = []
        for obj_type, relation in USER_DIRECT_RELATIONS:
            try:
                objs = await self.list_objects(
                    user_subject=f"user:{user_id}",
                    relation=relation,
                    object_type=obj_type,
                )
            except Exception:
                continue  # 该 type/relation 不在已部署 model 里 → 跳过
            for oid in objs:
                try:
                    resp = await self._client.read(ReadRequestTupleKey(  # type: ignore[no-untyped-call]
                        user=f"user:{user_id}", relation=relation,
                        object=f"{obj_type}:{oid}",
                    ))
                except Exception:
                    continue
                for t in resp.tuples:
                    deletes.append(ClientTuple(
                        user=t.key.user, relation=t.key.relation, object=t.key.object,
                    ))
        if not deletes:
            return 0
        BATCH = 50
        total = 0
        for i in range(0, len(deletes), BATCH):
            await self._client.write(ClientWriteRequest(deletes=deletes[i : i + BATCH]))
            total += len(deletes[i : i + BATCH])
        log.info("revoke_user_completely user=%s deleted=%d", user_id, total)
        return total

    # ───────────────────────── organization 同步 ──────────────────────────────
    async def add_user_to_organization(
        self, *, organization_tenant_key: str, user_id: str
    ) -> None:
        """user 登录时加入 org member。"""
        await self._client.write(
            ClientWriteRequest(
                writes=[
                    ClientTuple(
                        user=f"user:{user_id}",
                        relation="member",
                        object=f"organization:{organization_tenant_key}",
                    )
                ]
            )
        )

    # ───────────────────────── admin 判定 helpers ────────────────────────────
    async def is_org_admin(self, *, user_id: str, organization_tenant_key: str) -> bool:
        """是否企业管理员(organization.admin)。"""
        return await self.check(
            user_subject=f"user:{user_id}",
            relation="admin",
            object_type="organization",
            object_id=organization_tenant_key,
        )

    async def has_any_project_admin(self, *, user_id: str) -> bool:
        """user 是否对任意 project 有 can_admin(管理后台 polish 用)。"""
        ids = await self.list_objects(
            user_subject=f"user:{user_id}",
            relation="can_admin",
            object_type="project",
        )
        return len(ids) > 0

    async def add_user_to_group(self, *, group_id: str, user_id: str) -> None:
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

    async def remove_user_from_group(self, *, group_id: str, user_id: str) -> None:
        """从组移除成员:删 group:<id>#member tuple(#150 本地组管理用)。"""
        await self._client.write(
            ClientWriteRequest(
                deletes=[
                    ClientTuple(
                        user=f"user:{user_id}",
                        relation="member",
                        object=f"group:{group_id}",
                    )
                ]
            )
        )

    async def list_group_member_tuples(self, group_id: str) -> list[tuple[str, str, str]]:
        """group 对象上全部 tuple 的 (user, relation, object) — 删组时清理用。

        只列以 group:<id> 为 *object* 的 member tuple(成员关系);
        group#member 作为 *subject* 出现在 project/folder 上的引用按 department 处理
        惯例(ADR-0007:存量 tuple 保留原样)不回收。
        """
        from openfga_sdk.models import ReadRequestTupleKey
        resp = await self._client.read(ReadRequestTupleKey(  # type: ignore[no-untyped-call]
            object=f"group:{group_id}"))
        return [
            (t.key.user, t.key.relation, t.key.object)
            for t in resp.tuples
            if t.key.relation == "member" and t.key.user.startswith("user:")
        ]

    # ───────────────────────── 时间限定下载 grant(approval download)─────────
    async def grant_explicit_download(
        self,
        *,
        user_id: str,
        object_type: Literal["project", "asset", "folder"],
        object_id: str,
        duration_seconds: int,
    ) -> None:
        """审批通过的临时下载 grant — project / folder / asset 三级。
        #129: 加 folder(model 已 condition 化,跟 project/asset 一致)。

        到期自动失效(non_expired_grant condition,无需 cron 清理)。

        重复 grant(同 user+object 已存在)→ 先 delete 再 write 新的(更新 grant_time)。
        """
        grant_time = datetime.now(timezone.utc).isoformat()
        new_tuple = ClientTuple(
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
        try:
            await self._client.write(ClientWriteRequest(writes=[new_tuple]))
        except Exception as e:
            # 'tuple already existed' → 先删后写(刷新 condition.grant_time)
            if is_already_exists_error(e):
                try:
                    await self._client.write(ClientWriteRequest(deletes=[
                        ClientTuple(
                            user=f"user:{user_id}",
                            relation="explicit_downloader",
                            object=f"{object_type}:{object_id}",
                        )
                    ]))
                except Exception:  # noqa: BLE001
                    pass
                await self._client.write(ClientWriteRequest(writes=[new_tuple]))
            else:
                raise
        log.info("grant explicit_download user=%s %s=%s ttl=%ds",
                 user_id, object_type, object_id, duration_seconds)

    async def revoke_explicit_download(
        self,
        *,
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


async def create_permissions_service(settings: Settings) -> PermissionsService:
    svc = PermissionsService(settings)
    try:
        await svc._client.read_authorization_models()
    except Exception as e:
        log.warning("OpenFGA init check failed: %s", e)
    return svc
