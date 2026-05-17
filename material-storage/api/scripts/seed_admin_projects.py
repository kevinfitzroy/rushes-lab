"""为每个 active user 创建一个"个人管理"项目 + 医美短视频主题的标准 5 层文件夹结构。

每个 user → 1 个 project(以 user 的 name 命名),user 自己作为项目 admin。
项目结构(适配医美短视频内容创作流程):

  <name>-rushes/
    01-客户原片(sensitive)/          ← 治疗前后照片、面诊视频;限邀请才能进
    02-工作素材/                       ← 拍摄花絮、镜头素材、空镜
      02a-面诊与术前/
      02b-治疗中过程/
      02c-术后恢复/
    03-成片与剪辑/                     ← 短视频成片、剪辑工程文件
      03a-小红书竖版/
      03b-抖音竖版/
      03c-视频号方版/
    04-平面与封面/                     ← 海报、九宫格、封面图
    05-音乐与字幕模板/                 ← BGM、字幕模板、转场素材

用法:
  docker exec ms-api python -m scripts.seed_admin_projects                 # dry-run 看清单
  docker exec ms-api python -m scripts.seed_admin_projects --apply         # 真创建
  docker exec ms-api python -m scripts.seed_admin_projects --apply --only ou_xxx,ou_yyy  # 只给指定 user
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.session import get_sessionmaker
from app.db.tables import Folder, Organization, Project, User
from app.services.contact_sync import get_default_organization
from app.services.permissions import create_permissions_service
from app.settings import get_settings

logging.basicConfig(level=logging.INFO, format="%(levelname)s — %(message)s")
log = logging.getLogger("seed-admin-projects")


# ─── folder tree spec(医美短视频)─────────────────────────────────────────────
# 每条 = (name, is_sensitive, [children])
TREE: list[tuple[str, bool, list]] = [
    ("01-客户原片", True, []),  # sensitive — 限一级
    ("02-工作素材", False, [
        ("02a-面诊与术前", False, []),
        ("02b-治疗中过程", False, []),
        ("02c-术后恢复", False, []),
    ]),
    ("03-成片与剪辑", False, [
        ("03a-小红书竖版", False, []),
        ("03b-抖音竖版", False, []),
        ("03c-视频号方版", False, []),
    ]),
    ("04-平面与封面", False, []),
    ("05-音乐与字幕模板", False, []),
]


def slugify(name: str, fallback: str) -> str:
    """user.name → 项目 code 前缀(简单 ASCII fallback);全中文 → fallback。"""
    import re
    s = name.strip().lower()
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^a-z0-9-]", "", s)  # 去掉中文等
    return s or fallback


async def _create_folder_tree(
    db, permissions, project_id: uuid.UUID, project_code: str,
    spec: list[tuple[str, bool, list]],
    parent_folder_id: uuid.UUID | None = None,
    parent_prefix: str = "",
) -> int:
    """递归建文件夹 + 写 OpenFGA tuples。返计数。"""
    count = 0
    for name, is_sensitive, children in spec:
        prefix = f"{parent_prefix}{name}/" if parent_prefix else f"{project_code}/{name}/"
        folder = Folder(
            id=uuid.uuid4(),
            project_id=project_id,
            parent_folder_id=parent_folder_id,
            name=name,
            minio_prefix=prefix,
            is_sensitive=is_sensitive,
        )
        db.add(folder)
        try:
            await db.commit()
        except IntegrityError as e:
            await db.rollback()
            log.warning("    skip(prefix 冲突):%s", e.orig)
            continue
        count += 1
        if is_sensitive:
            await permissions.bootstrap_sensitive_folder(
                folder_id=str(folder.id), project_id=str(project_id),
            )
        else:
            if parent_folder_id is None:
                await permissions.bootstrap_folder(
                    folder_id=str(folder.id),
                    parent_type="project",
                    parent_id=str(project_id),
                )
            else:
                await permissions.bootstrap_folder(
                    folder_id=str(folder.id),
                    parent_type="folder",
                    parent_id=str(parent_folder_id),
                )
        # 递归子目录(sensitive 不能有子目录,model v4 已限)
        if children and not is_sensitive:
            count += await _create_folder_tree(
                db, permissions, project_id, project_code,
                children,
                parent_folder_id=folder.id,
                parent_prefix=prefix,
            )
    return count


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="真创建(否则只 dry-run 打印清单)")
    parser.add_argument("--only", default="",
                        help="只处理指定 open_id 逗号分隔(默认全部 active user)")
    args = parser.parse_args()

    settings = get_settings()
    perms = await create_permissions_service(settings)
    sm = get_sessionmaker()

    async with sm() as db:
        org = await get_default_organization(db)
        if not org:
            log.error("no default organization configured(.env DEFAULT_ORGANIZATION_ID)")
            await perms.close()
            return 1
        org_id, tenant_key = org
        org_row = await db.get(Organization, org_id)
        if not org_row:
            log.error("default org %s not found in db", org_id)
            await perms.close()
            return 2

        only_ids = {s.strip() for s in args.only.split(",") if s.strip()}
        stmt = select(User).where(User.is_active.is_(True))
        if only_ids:
            stmt = stmt.where(User.feishu_open_id.in_(only_ids))
        users = list((await db.execute(stmt)).scalars().all())

        if not users:
            log.warning("no active users matched")
            await perms.close()
            return 0

        log.info("=== plan(%d users)===", len(users))
        plan: list[tuple[User, str, str]] = []
        for u in users:
            short = str(u.id)[:8]
            slug = slugify(u.name, fallback=f"u-{short}")
            code = f"{slug}-rushes-{short}" if not slug.startswith("u-") else f"{slug}-rushes"
            existing = (await db.execute(
                select(Project).where(Project.code == code)
            )).scalar_one_or_none()
            tag = "[SKIP exists]" if existing else "[NEW]"
            display = f"{u.name}({u.feishu_open_id[:12]}…)"
            log.info("  %s %s  →  project code=%s", tag, display, code)
            if not existing:
                plan.append((u, slug, code))

        if not args.apply:
            log.info("\n--apply 未传 — dry-run 结束。共 %d 个新项目会被创建", len(plan))
            await perms.close()
            return 0

        log.info("\n=== applying(%d new projects)===", len(plan))
        ok, fail = 0, 0
        for u, slug, code in plan:
            try:
                # 1) 建 project 行
                project = Project(
                    id=uuid.uuid4(),
                    organization_id=org_id,
                    code=code,
                    name=f"{u.name} · 个人素材库",
                    description=f"{u.name} 的医美短视频工作素材库(seed_admin_projects 生成)",
                    minio_bucket=settings.minio_default_bucket,
                    visibility="private",
                )
                db.add(project)
                await db.commit()
                # 2) bootstrap project → org + user 作为 admin
                await perms.bootstrap_project(
                    project_id=str(project.id),
                    organization_tenant_key=tenant_key,
                    creator_open_id=u.feishu_open_id,
                )
                # 3) 建 folder tree
                n_folders = await _create_folder_tree(
                    db, perms, project.id, code, TREE,
                )
                log.info("  ✓ %s  → project %s + %d folders",
                         u.name, str(project.id)[:8], n_folders)
                ok += 1
            except Exception as e:  # noqa: BLE001
                fail += 1
                log.error("  ✗ %s  err=%s", u.name, e)
                await db.rollback()

        log.info("\n=== done: %d ok / %d fail ===", ok, fail)

    await perms.close()
    return 0 if not fail else 3


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
