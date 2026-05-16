"""通讯录同步核心服务 — a2 iter:event handler / 冷启动同步共用。

输入:飞书 user / department / group 的 payload(API 返或 webhook event)
输出:upsert DB users 表 + 写 OpenFGA tuples(add_user_to_organization /
      add_user_to_department / add_user_to_group / add_department_as_subdept)
      或撤销(remove_user_from_department / revoke_user_completely)

idempotent:重复跑无副作用(用 ON CONFLICT 或 OpenFGA write 幂等)。
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.tables import Organization, User
from app.services.permissions import PermissionsService

log = logging.getLogger(__name__)


# ─── helpers ─────────────────────────────────────────────────────────────────
def _user_uuid_from_open_id(open_id: str) -> uuid.UUID:
    """deterministic UUID for users.id derived from open_id(避免 OIDC 登录 vs sync race)。"""
    return uuid.uuid5(uuid.NAMESPACE_DNS, f"feishu:user:{open_id}")


# ─── user upsert ─────────────────────────────────────────────────────────────
async def upsert_user(
    db: AsyncSession,
    *,
    open_id: str,
    union_id: str | None = None,
    name: str = "",
    email: str | None = None,
    organization_id: uuid.UUID | None = None,
    is_active: bool = True,
) -> User:
    """飞书 user payload → DB users 表 upsert。

    主键策略:internal UUID = uuid5(NAMESPACE_DNS, "feishu:user:{open_id}"),
      避免 OIDC 登录 / contact event / cold-sync 三处不同 uuid4 重复插入。
    """
    user_id = _user_uuid_from_open_id(open_id)
    stmt = (
        pg_insert(User)
        .values(
            id=user_id,
            feishu_open_id=open_id,
            feishu_union_id=union_id,
            name=name or "unknown",
            email=email,
            organization_id=organization_id,
            is_active=is_active,
        )
        .on_conflict_do_update(
            index_elements=["feishu_open_id"],
            set_={
                "feishu_union_id": union_id,
                "name": name or "unknown",
                "email": email,
                "is_active": is_active,
                # organization_id 只在原值为 null 时覆盖(避免清空老的)
                # 实际:SQL COALESCE 在 ON CONFLICT 用 EXCLUDED 表达式
            },
        )
        .returning(User)
    )
    res = await db.execute(stmt)
    user = res.scalar_one()
    # 单独处理 organization_id 兜底
    if organization_id is not None and user.organization_id is None:
        user.organization_id = organization_id
    await db.commit()
    await db.refresh(user)
    return user


# ─── 主入口:同步一个 user(API 返 / event 拿到的 payload)────────────────────
async def sync_user(
    db: AsyncSession,
    permissions: PermissionsService,
    *,
    user_obj: dict[str, Any],
    organization_tenant_key: str,
    organization_id: uuid.UUID,
    previous_department_ids: list[str] | None = None,
) -> User:
    """同步一个飞书 user 完整状态:DB upsert + OpenFGA tuples。

    user_obj:飞书 API / event payload 的 user dict(open_id / name / email /
              department_ids[] / status.is_resigned 等)
    previous_department_ids:旧部门列表(仅 updated 事件可用,用于 diff 删旧 tuple);
                            None 时 = 全量重建(冷启动 / created 事件)
    """
    open_id = user_obj.get("open_id")
    if not open_id:
        raise ValueError("sync_user: open_id missing")

    status = user_obj.get("status") or {}
    is_resigned = bool(status.get("is_resigned"))
    is_activated = bool(status.get("is_activated", True))
    is_active = is_activated and not is_resigned

    # 1) DB upsert
    user = await upsert_user(
        db,
        open_id=open_id,
        union_id=user_obj.get("union_id"),
        name=user_obj.get("name", ""),
        email=user_obj.get("email") or user_obj.get("enterprise_email"),
        organization_id=organization_id,
        is_active=is_active,
    )
    if is_resigned and user.resigned_at is None:
        user.resigned_at = datetime.now(timezone.utc)
        await db.commit()

    # 2) 离职 → 全 OpenFGA tuple 撤
    if not is_active:
        try:
            n = await permissions.revoke_user_completely(open_id)
            log.info("sync_user revoked %d tuples for resigned/inactive user=%s", n, open_id)
        except Exception as e:  # noqa: BLE001
            log.warning("sync_user revoke fail user=%s err=%s", open_id, e)
        return user

    # 3) OpenFGA org member
    try:
        await permissions.add_user_to_organization(
            organization_tenant_key=organization_tenant_key, user_open_id=open_id,
        )
    except Exception as e:  # noqa: BLE001
        log.debug("add_user_to_organization tolerate: %s", e)

    # 4) 部门 tuples — diff 模式
    new_dept_ids = list(user_obj.get("department_ids") or [])
    if previous_department_ids is not None:
        prev = set(previous_department_ids)
        new = set(new_dept_ids)
        for dep in prev - new:
            try:
                await permissions.remove_user_from_department(
                    department_id=dep, user_open_id=open_id,
                )
                log.info("sync_user remove user=%s from dept=%s", open_id, dep)
            except Exception as e:  # noqa: BLE001
                log.debug("remove_user_from_department tolerate: %s", e)
        for dep in new - prev:
            try:
                await permissions.add_user_to_department(
                    department_id=dep, user_open_id=open_id,
                )
                log.info("sync_user add user=%s to dept=%s", open_id, dep)
            except Exception as e:  # noqa: BLE001
                log.debug("add_user_to_department tolerate: %s", e)
    else:
        # 全量重建(冷启动 / created 事件)
        for dep in new_dept_ids:
            try:
                await permissions.add_user_to_department(
                    department_id=dep, user_open_id=open_id,
                )
            except Exception as e:  # noqa: BLE001
                log.debug("add_user_to_department tolerate: %s", e)

    return user


# ─── department 嵌套 ─────────────────────────────────────────────────────────
async def sync_department_parent(
    permissions: PermissionsService,
    *,
    department_id: str,
    parent_department_id: str | None,
    previous_parent_department_id: str | None = None,
) -> None:
    """部门 parent 变更同步 — 改 OpenFGA department#member nesting tuple。

    department#member rel:子部门 #member 自动算父部门 #member。
    parent 为根部门(顶级)时不写 nesting tuple。
    """
    # 删旧
    if previous_parent_department_id and previous_parent_department_id != parent_department_id:
        try:
            from openfga_sdk.client.models import ClientTuple, ClientWriteRequest
            await permissions._client.write(  # type: ignore[attr-defined]
                ClientWriteRequest(deletes=[
                    ClientTuple(
                        user=f"department:{department_id}#member",
                        relation="member",
                        object=f"department:{previous_parent_department_id}",
                    ),
                ])
            )
        except Exception as e:  # noqa: BLE001
            log.debug("remove subdept tolerate: %s", e)

    if parent_department_id:
        try:
            await permissions.add_department_as_subdept(
                parent_department_id=parent_department_id,
                child_department_id=department_id,
            )
        except Exception as e:  # noqa: BLE001
            log.debug("add subdept tolerate: %s", e)


# ─── 离职闭环 ────────────────────────────────────────────────────────────────
async def handle_user_deleted(
    db: AsyncSession,
    permissions: PermissionsService,
    *,
    open_id: str,
) -> int:
    """contact.user.deleted_v3:删 OpenFGA tuple + DB is_active=false + resigned_at=now。

    返被撤的 OpenFGA tuple 数。
    """
    # 1) 找 db user
    from sqlalchemy import select
    res = await db.execute(select(User).where(User.feishu_open_id == open_id))
    user = res.scalar_one_or_none()
    if user is not None:
        user.is_active = False
        if user.resigned_at is None:
            user.resigned_at = datetime.now(timezone.utc)
        await db.commit()
    # 2) OpenFGA revoke
    try:
        n = await permissions.revoke_user_completely(open_id)
        log.info("handle_user_deleted revoked %d tuples user=%s", n, open_id)
        return n
    except Exception as e:  # noqa: BLE001
        log.warning("handle_user_deleted revoke fail user=%s err=%s", open_id, e)
        return 0


# ─── 找 default org ──────────────────────────────────────────────────────────
async def get_default_organization(db: AsyncSession) -> tuple[uuid.UUID, str] | None:
    """从 settings.default_organization_id 拿 + db 查 tenant_key。"""
    from app.settings import get_settings
    settings = get_settings()
    if not settings.default_organization_id:
        return None
    org_id = uuid.UUID(settings.default_organization_id)
    org = await db.get(Organization, org_id)
    if org is None:
        return None
    tenant_key = org.feishu_tenant_key or str(org_id)
    return org_id, tenant_key
