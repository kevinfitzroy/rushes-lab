"""给指定 user 设本地登录密码 / 登录名 — dev 与生产运维两用(runbook §8.2)。

执行(容器内,与其它 seed 同款):
  docker compose exec ms-api python -m scripts.set_password <用户名|邮箱|显示名|UUID> \
      [--password <明文>] [--username <登录名>] [--must-change] [--list]

行为:
  - identifier 按 local_login 同款优先级匹配:username → email(含 @)→ name → UUID
  - 设 users.password_hash(argon2id),默认同时清 must_change_password
    (seed 出来的账号直接可登录;--must-change 则保留强制改密,用于测首登流程)
  - --username 给老账号(如 dev_bootstrap 的 alice/bob,username 为 NULL)补登录名
  - 省略 --password 时生成一次性临时密码并回显一次(与管理后台同款策略)
  - --list 列出全部用户及 password_set / must_change 状态,方便核对测试账号

场景:
  - local_up.sh 收尾时给 alice/bob/evan/outsider 设固定 dev 密码,浏览器走
    /login 账号密码登录测角色(与生产同链路,不再依赖 X-User-Id dev 通道)
  - 生产:管理员重置某用户密码(结果只打印到 stdout,自行线下传递)
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import uuid
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_sessionmaker
from app.db.tables import User
from app.services.local_auth import LocalAuthService
from app.services.passwords import generate_temp_password
from app.settings import get_settings

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s — %(message)s")
log = logging.getLogger("set_password")


async def find_user(db: AsyncSession, identifier: str) -> User | None:
    """与 LocalAuthService.find_user_by_username 同优先级,外加 UUID 直查。"""
    try:
        uid = uuid.UUID(identifier)
        return await db.get(User, uid)
    except ValueError:
        pass
    lowered = identifier.lower()
    for column in (User.username, User.email, User.name):
        if column is User.email and "@" not in lowered:
            continue
        res = await db.execute(
            select(User).where(func.lower(column) == lowered).limit(2)
        )
        users = list(res.scalars())
        if len(users) == 1:
            return users[0]
        if len(users) > 1:
            raise SystemExit(f"ERROR: identifier '{identifier}' 命中多条 {column.key},请改用 UUID")
    return None


async def list_users() -> None:
    sm = get_sessionmaker()
    async with sm() as session:
        res = await session.execute(select(User).order_by(User.name))
        rows = list(res.scalars())
    print(f"{'id':<38} {'username':<12} {'name':<20} pw  must_change")
    for u in rows:
        print(
            f"{str(u.id):<38} {u.username or '-':<12} {u.name:<20} "
            f"{'✓' if u.password_hash else '·'}   {'⚠' if u.must_change_password else '·'}"
        )


async def set_password(identifier: str, password: str | None, new_username: str | None,
                       must_change: bool) -> None:
    settings = get_settings()
    # hash / verify / policy 不碰 redis;构造未连接客户端仅满足签名
    local_auth = LocalAuthService(settings, Redis())

    if password is not None:
        policy_error = local_auth.validate_password_policy(password)
        if policy_error:
            raise SystemExit(f"ERROR: {policy_error}")
    sm = get_sessionmaker()
    async with sm() as session:
        user = await find_user(session, identifier)
        if user is None:
            raise SystemExit(f"ERROR: 找不到用户 '{identifier}'(--list 查看全部)")

        if new_username:
            res = await session.execute(
                select(User).where(func.lower(User.username) == new_username.lower())
                .where(User.id != user.id).limit(1)
            )
            if res.scalars().first() is not None:
                raise SystemExit(f"ERROR: username '{new_username}' 已被占用")
            user.username = new_username

        final_password = password or generate_temp_password()
        user.password_hash = local_auth.hash_password(final_password)
        user.must_change_password = must_change
        await session.commit()

        print("---SET_PASSWORD RESULT---")
        print(f"user_id={user.id}")
        print(f"username={user.username or '-'}")
        print(f"name={user.name}")
        print(f"must_change_password={user.must_change_password}")
        if password is None:
            print(f"temp_password={final_password}   # 只显示这一次,请立即保存")
        print(f"登录:http://localhost:5173/ms-static/web/login(用户名 {user.username or user.name})")


def main() -> None:
    parser = argparse.ArgumentParser(description="设本地登录密码 / 登录名")
    parser.add_argument("identifier", nargs="?", help="username / email / 显示名 / UUID")
    parser.add_argument("--password", help="明文密码;省略则生成一次性临时密码")
    parser.add_argument("--username", help="补设/改本地登录名(如给 seed 账号设 alice)")
    parser.add_argument("--must-change", action="store_true",
                        help="保留 must_change_password(测首登强制改密);默认清除")
    parser.add_argument("--list", action="store_true", help="列出全部用户及密码状态")
    args: argparse.Namespace = parser.parse_args()

    if args.list:
        asyncio.run(list_users())
        return
    if not args.identifier:
        parser.error("需要 identifier(或 --list)")
    kw: dict[str, Any] = {
        "password": args.password,
        "new_username": args.username,
        "must_change": args.must_change,
    }
    asyncio.run(set_password(args.identifier, **kw))


if __name__ == "__main__":
    main()
