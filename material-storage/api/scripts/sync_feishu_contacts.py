"""冷启动同步:拉飞书全量 user / department / group → DB + OpenFGA。

执行:
  docker exec ms-api python -m scripts.sync_feishu_contacts

行为(idempotent):
  1. 通过 contact/v3/scopes 拿 app 可见顶级部门 / user / group
  2. 递归子部门 + 写 OpenFGA department#member nesting tuples
  3. 列每个部门的 user → DB upsert + OpenFGA add_user_to_organization/department
  4. 列 group → 列 member → OpenFGA add_user_to_group

前置(飞书后台):
  - 应用功能 → 通讯录 → 可见性范围(全公司 / 指定部门)
  - 权限:contact:contact.base:readonly + contact:department.base:readonly +
          contact:user.base:readonly + contact:group:readonly

如果 OpenAPI 返 403(权限不足),脚本会 log warning + 跳过,不爆炸。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.db.session import get_sessionmaker
from app.services.contact_sync import get_default_organization, sync_user
from app.services.feishu_client import create_feishu_client
from app.services.feishu_contact import FeishuContactClient
from app.services.permissions import create_permissions_service
from app.settings import get_settings

logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
log = logging.getLogger("contact-sync")


async def main() -> None:
    settings = get_settings()
    sm = get_sessionmaker()

    permissions = await create_permissions_service(settings)
    feishu = await create_feishu_client(settings)
    contact = FeishuContactClient(feishu)

    if not settings.feishu_im_enabled:
        log.error("feishu_im_enabled=false → tenant_access_token 未初始化,跳过")
        return

    async with sm() as db:
        org = await get_default_organization(db)
    if org is None:
        log.error("settings.default_organization_id 未配 / org 未在 db,跳过")
        return
    org_id, tenant_key = org
    log.info("default org: id=%s tenant_key=%s", org_id, tenant_key)

    # 1) 拉 app 可见范围
    scopes = await contact.get_scopes()
    top_depts = scopes["department_ids"]
    top_users = scopes["user_ids"]
    top_groups = scopes["group_ids"]
    log.info("scopes: %d top depts, %d top users, %d top groups",
             len(top_depts), len(top_users), len(top_groups))

    # 2) 递归部门 → BFS
    all_depts: list[str] = []
    parent_of: dict[str, str | None] = {}
    queue = [(d, None) for d in top_depts]
    while queue:
        dept_id, parent = queue.pop(0)
        if dept_id in parent_of:
            continue
        all_depts.append(dept_id)
        parent_of[dept_id] = parent
        children_cnt = 0
        async for child in contact.list_child_departments(dept_id):
            child_id = child.get("open_department_id") or child.get("department_id")
            if child_id and child_id not in parent_of:
                queue.append((child_id, dept_id))
                children_cnt += 1
        log.info("dept %s: %d children", dept_id, children_cnt)
    log.info("traversed %d departments total", len(all_depts))

    # 3) 写部门嵌套 tuples
    for dept_id, parent in parent_of.items():
        if parent:
            try:
                await permissions.add_department_as_subdept(
                    parent_department_id=parent, child_department_id=dept_id,
                )
            except Exception as e:  # noqa: BLE001
                log.debug("add_department_as_subdept tolerate: %s", e)
    log.info("dept nesting tuples written")

    # 4) 列每部门 user → sync(全量重建模式,不 diff)
    total_users = 0
    seen_open_ids: set[str] = set()
    for dept_id in all_depts:
        async for u in contact.list_users_in_department(dept_id):
            open_id = u.get("open_id")
            if not open_id or open_id in seen_open_ids:
                continue
            seen_open_ids.add(open_id)
            async with sm() as db:
                try:
                    await sync_user(
                        db, permissions,
                        user_obj=u,
                        organization_tenant_key=tenant_key,
                        organization_id=org_id,
                        previous_department_ids=None,
                    )
                    total_users += 1
                    if total_users % 20 == 0:
                        log.info("synced %d users so far…", total_users)
                except Exception as e:  # noqa: BLE001
                    log.warning("sync_user fail open_id=%s err=%s", open_id, e)
    log.info("synced %d users from departments", total_users)

    # 顶级 user(不在任何部门下)
    for top_uid in top_users:
        if top_uid in seen_open_ids:
            continue
        u = await contact.get_user(top_uid)
        if u is None:
            continue
        async with sm() as db:
            await sync_user(
                db, permissions,
                user_obj=u,
                organization_tenant_key=tenant_key,
                organization_id=org_id,
                previous_department_ids=None,
            )
            seen_open_ids.add(top_uid)
            total_users += 1
    log.info("total synced users: %d", total_users)

    # 5) 用户组 → 成员
    group_count = 0
    group_member_count = 0
    async for g in contact.list_groups():
        gid = g.get("id")
        if not gid:
            continue
        group_count += 1
        async for m in contact.list_group_members(gid):
            mid = m.get("member_id")
            if not mid:
                continue
            try:
                await permissions.add_user_to_group(group_id=gid, user_open_id=mid)
                group_member_count += 1
            except Exception as e:  # noqa: BLE001
                log.debug("add_user_to_group tolerate: %s", e)
    log.info("synced %d groups with %d members", group_count, group_member_count)

    await feishu.close()
    await permissions.close()
    log.info("DONE — %d depts · %d users · %d groups",
             len(all_depts), total_users, group_count)


if __name__ == "__main__":
    asyncio.run(main())
