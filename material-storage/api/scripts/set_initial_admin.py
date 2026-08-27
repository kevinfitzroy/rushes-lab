"""引导「第一个能登录的管理员」—— 内网首次部署的必备一步。

## 为什么需要它

ADR-0007 之后账号由系统 admin 在管理后台创建并下发临时密码,但**第一个** admin
没有上游可依赖:

- `ENV=production` 下 `X-User-Id` 开发通道直接失效(`deps.py`),进不去;
- `seed_demo_data` / `dev_bootstrap` 只建用户行与授权 tuple,**不设密码**;
- 于是新装的内网机器没有任何可登录的账号 —— 部署完却进不去系统。

本脚本补上这一步:给指定用户设密码(可顺带创建用户、授予系统 admin)。

## 用法

    # 给已有用户设密码(不传 --password 则生成合规临时密码并打印)
    docker compose exec ms-api python -m scripts.set_initial_admin evan

    # 新机器从零开一个管理员:建用户 + 设密码 + 授予系统 admin
    docker compose exec ms-api python -m scripts.set_initial_admin admin \\
        --create --name "系统管理员" --email admin@example.com --grant-org-admin

    # 指定密码,且首次登录不强制改密
    docker compose exec ms-api python -m scripts.set_initial_admin evan \\
        --password 'YourStrongPw123' --no-force-change

默认 `must_change_password=true` —— 临时密码经过终端与运维记录,首次登录必须换掉
(后端会拦截除改密/me/logout 外的所有端口,见 review F15)。

系统 admin 关系与 `scripts/grant_org_admin.py` 一致:`organization:<tenant_key>#admin`。
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import uuid

from openfga_sdk.client.models import ClientTuple, ClientWriteRequest
from sqlalchemy import func, select

from app.db.session import get_sessionmaker
from app.db.tables import User
from app.services.org import get_default_organization
from app.services.passwords import generate_temp_password, hash_password
from app.services.permissions import create_permissions_service
from app.settings import get_settings

logging.basicConfig(level=logging.INFO, format="%(levelname)s — %(message)s")
log = logging.getLogger("set-initial-admin")


def _check_policy(password: str, min_length: int) -> str | None:
    """与 services/local_auth.py 的 validate_password_policy 同口径。

    这里不直接复用 LocalAuthService:它的构造需要 redis 连接(限流用),
    而本脚本只做一次性写库,不该为此拉起 redis 依赖。
    """
    if len(password) < min_length:
        return f"密码长度至少 {min_length} 位"
    if not any(c.isalpha() for c in password):
        return "密码必须包含字母"
    if not any(c.isdigit() for c in password):
        return "密码必须包含数字"
    return None


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="设置首个可登录管理员(内网首次部署引导)",
    )
    parser.add_argument("username", help="登录名(拼音/工号友好,不强制邮箱格式)")
    parser.add_argument("--password", help="指定密码;省略则生成合规临时密码并打印")
    parser.add_argument("--create", action="store_true", help="用户不存在时创建")
    parser.add_argument("--name", help="显示名(仅 --create 时使用;默认取 username)")
    parser.add_argument("--email", help="邮箱(仅 --create 时使用)")
    parser.add_argument(
        "--grant-org-admin", action="store_true",
        help="同时授予系统 admin(organization#admin,建项目/进 /admin/* 必需)",
    )
    parser.add_argument(
        "--no-force-change", action="store_true",
        help="不要求首次登录改密(默认要求)",
    )
    args = parser.parse_args()

    settings = get_settings()
    username = args.username.strip()
    if not username:
        log.error("username 不能为空")
        return 2

    password = args.password or generate_temp_password()
    generated = args.password is None
    if (err := _check_policy(password, settings.auth_password_min_length)) is not None:
        log.error("密码不符合策略:%s", err)
        return 2

    sm = get_sessionmaker()
    async with sm() as db:
        # username 大小写不敏感匹配,与登录侧 find_user_by_username 一致
        user = (
            await db.execute(
                select(User).where(func.lower(User.username) == username.lower()).limit(2)
            )
        ).scalars().first()

        if user is None and not args.create:
            log.error(
                "用户不存在:%s(加 --create 可直接创建,或先用管理后台建号)", username
            )
            return 1

        if user is None:
            user = User(
                id=uuid.uuid4(),
                username=username,
                name=args.name or username,
                email=args.email,
                is_active=True,
            )
            db.add(user)
            log.info("创建用户 %s(%s)", username, user.id)
        elif not user.is_active:
            user.is_active = True
            log.info("用户已禁用 → 重新启用")

        user.password_hash = hash_password(password)
        user.must_change_password = not args.no_force_change
        await db.commit()
        user_id = str(user.id)

    if args.grant_org_admin:
        perms = await create_permissions_service(settings)
        try:
            async with sm() as db:
                org = await get_default_organization(db)
            if not org:
                log.error(
                    "没有默认组织(检查 .env 的 DEFAULT_ORGANIZATION_ID 与 organizations 表);"
                    "密码已设置,但系统 admin 未授予"
                )
                return 1
            _, tenant_key = org
            try:
                await perms._client.write(
                    ClientWriteRequest(writes=[
                        ClientTuple(
                            user=f"user:{user_id}",
                            relation="admin",
                            object=f"organization:{tenant_key}",
                        )
                    ])
                )
                log.info("已授予系统 admin(organization:%s#admin)", tenant_key)
            except Exception as e:
                # 已存在同名 tuple 时 OpenFGA 返回 400,视作幂等成功
                log.info("系统 admin tuple 已存在或写入被拒:%s", e)
        finally:
            await perms.close()

    print("---INITIAL ADMIN---")
    print(f"USER_ID={user_id}")
    print(f"USERNAME={username}")
    if generated:
        print(f"PASSWORD={password}        # 自动生成,仅此一次输出")
    else:
        print("PASSWORD=<你指定的值>")
    print(f"MUST_CHANGE_PASSWORD={'true' if not args.no_force_change else 'false'}")
    print(f"ORG_ADMIN={'true' if args.grant_org_admin else 'false'}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
