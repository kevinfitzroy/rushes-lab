"""后台指定系统 admin — 不可 UI promote/demote(默认 1 个,可加多个)。

用法:
  docker exec ms-api python -m scripts.grant_org_admin ou_xxx           # add
  docker exec ms-api python -m scripts.grant_org_admin --revoke ou_xxx  # remove
  docker exec ms-api python -m scripts.grant_org_admin --list           # 列当前所有

系统 admin = OpenFGA `organization:<tenant_key>#admin` 关系。
只有系统 admin 可创建项目。普通用户只能由系统 admin 通过 ProjectMembersDrawer 添加为
项目成员(任意 role)。
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from openfga_sdk.client.models import ClientTuple, ClientWriteRequest

from app.db.session import get_sessionmaker
from app.services.contact_sync import get_default_organization
from app.services.permissions import create_permissions_service
from app.settings import get_settings

logging.basicConfig(level=logging.INFO, format="%(levelname)s — %(message)s")
log = logging.getLogger("grant-org-admin")


async def main() -> int:
    parser = argparse.ArgumentParser(description="系统 admin 管理(后台命令)")
    parser.add_argument("open_id", nargs="?", help="飞书 open_id;--list 时可省")
    parser.add_argument("--revoke", action="store_true", help="撤销 admin")
    parser.add_argument("--list", action="store_true", help="列当前 admin")
    args = parser.parse_args()

    settings = get_settings()
    sm = get_sessionmaker()
    perms = await create_permissions_service(settings)

    async with sm() as db:
        org = await get_default_organization(db)
    if not org:
        log.error("no default organization configured(.env DEFAULT_ORGANIZATION_ID)")
        return 1
    _, tenant_key = org

    if args.list:
        admins = await perms.list_users_with_relation(
            object_type="organization", object_id=tenant_key, relation="admin",
        )
        if not admins:
            print("(no system admin)")
        else:
            for a in admins:
                print(a)
        await perms.close()
        return 0

    if not args.open_id:
        parser.error("open_id required(unless --list)")
        return 2

    op = "delete" if args.revoke else "write"
    tup = ClientTuple(
        user=f"user:{args.open_id}",
        relation="admin",
        object=f"organization:{tenant_key}",
    )
    try:
        if args.revoke:
            await perms._client.write(ClientWriteRequest(deletes=[tup]))
            log.info("revoked system admin: %s", args.open_id)
        else:
            await perms._client.write(ClientWriteRequest(writes=[tup]))
            log.info("granted system admin: %s", args.open_id)
    except Exception as e:  # noqa: BLE001
        log.error("%s fail: %s", op, e)
        await perms.close()
        return 3

    await perms.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
