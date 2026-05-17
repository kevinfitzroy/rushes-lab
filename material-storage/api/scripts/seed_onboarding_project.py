"""seed onboarding project — 创建一个 public 项目放操作手册 / 权限模型 / 示例素材。

每次部署后跑(deploy_server2.sh step 6.5),db 清空重建时用户立刻有上手内容。

执行:
  docker compose exec ms-api python -m scripts.seed_onboarding_project

输出:
  ONBOARDING_PROJECT_ID=...
  uploaded: <list of asset filename>

行为(idempotent;重复跑无副作用):
  1. 依赖 dev_bootstrap 已创建 organization + alice user(用 dev_admin_open_id);
     若没,本脚本会自己 upsert 一份 minimal organization + alice
  2. 创建 public project `demo-onboarding`
  3. 3 个 root folder:
       01-入门文档(普通)— 放操作手册.md + 权限模型.md
       02-示例素材(普通)— 放 PIL 生成的 placeholder PNG × 3
       03-敏感示例(sensitive)— 放敏感文件夹示例说明.md + 1 张 placeholder
  4. alice (dev_admin) → project admin
  5. sensitive folder 给 alice invited_downloader(沿用 PR #92 模式,避免"建了看不见")
  6. 所有文件上传到 MinIO + DB row + OpenFGA bootstrap tuple
"""
from __future__ import annotations

import asyncio
import io
import logging
import pathlib
import sys
import uuid

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy.dialects.postgresql import insert

from app.db.session import get_sessionmaker
from app.db.tables import Asset, Folder, Organization, Project, User
from app.services.permissions import create_permissions_service
from app.settings import get_settings

logging.basicConfig(level=logging.INFO, format="%(levelname)s — %(message)s")
log = logging.getLogger("seed-onboarding")

# 固定 UUID(idempotent)— 跟 dev_bootstrap 的 ORG_ID / ADMIN_USER_ID 对齐
ORG_ID = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
ADMIN_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
ADMIN_OPEN_ID = "dev_admin_open_id"
PROJECT_ID = uuid.UUID("22222222-2222-2222-2222-222222222001")
BUCKET = "ms-dev"

DOC_FOLDER_ID = uuid.uuid5(PROJECT_ID, "01-入门文档")
DEMO_FOLDER_ID = uuid.uuid5(PROJECT_ID, "02-示例素材")
SENSITIVE_FOLDER_ID = uuid.uuid5(PROJECT_ID, "03-敏感示例")

ASSETS_DIR = pathlib.Path(__file__).parent / "seed_assets"


def _placeholder_png(label: str, color: tuple[int, int, int]) -> bytes:
    """生成一张 1024x768 PNG,纯色背景 + 中央文字 label。"""
    img = Image.new("RGB", (1024, 768), color)
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 64)
    except OSError:
        font = ImageFont.load_default()
    # 居中
    bbox = draw.textbbox((0, 0), label, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((1024 - tw) / 2, (768 - th) / 2), label, fill=(255, 255, 255), font=font)
    sub = "seed placeholder · demo-onboarding"
    sub_bbox = draw.textbbox((0, 0), sub, font=ImageFont.load_default())
    sw = sub_bbox[2] - sub_bbox[0]
    draw.text(((1024 - sw) / 2, 768 - 40), sub, fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# (filename, content_bytes, content_type, folder_id) — 顺序即上传顺序
def _build_files() -> list[tuple[str, bytes, str, uuid.UUID]]:
    out: list[tuple[str, bytes, str, uuid.UUID]] = []
    # 01-入门文档
    for name in ("操作手册.md", "权限模型.md"):
        p = ASSETS_DIR / name
        if not p.exists():
            log.warning("missing seed asset %s, skip", name)
            continue
        out.append((name, p.read_bytes(), "text/markdown; charset=utf-8", DOC_FOLDER_ID))
    # 02-示例素材 — 3 张 placeholder PNG
    out.append(("示例图-蓝.png", _placeholder_png("示例 1", (60, 100, 180)),
                "image/png", DEMO_FOLDER_ID))
    out.append(("示例图-绿.png", _placeholder_png("示例 2", (60, 140, 90)),
                "image/png", DEMO_FOLDER_ID))
    out.append(("示例图-橙.png", _placeholder_png("示例 3", (200, 120, 60)),
                "image/png", DEMO_FOLDER_ID))
    # 03-敏感示例
    sp = ASSETS_DIR / "敏感文件夹示例说明.md"
    if sp.exists():
        out.append(("敏感文件夹示例说明.md", sp.read_bytes(),
                    "text/markdown; charset=utf-8", SENSITIVE_FOLDER_ID))
    out.append(("示例敏感图.png", _placeholder_png("敏感示例", (140, 60, 100)),
                "image/png", SENSITIVE_FOLDER_ID))
    return out


async def main() -> None:
    settings = get_settings()
    sm = get_sessionmaker()

    # ─── 1) DB upsert(org / alice / project / folders)─────────────────────
    async with sm() as session:
        # organization — 跟 dev_bootstrap 对齐;若 dev_bootstrap 已跑过会 no-op
        await session.execute(
            insert(Organization)
            .values(id=ORG_ID, name="dev-clinic", feishu_tenant_key=None)
            .on_conflict_do_nothing(index_elements=["id"])
        )
        # alice — 同样 minimal upsert(dev_bootstrap 跑过则 no-op)
        await session.execute(
            insert(User)
            .values(
                id=ADMIN_USER_ID,
                feishu_open_id=ADMIN_OPEN_ID,
                name="alice (admin)",
                email="alice@dev.local",
                is_active=True,
                organization_id=ORG_ID,
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )
        # project
        await session.execute(
            insert(Project)
            .values(
                id=PROJECT_ID,
                organization_id=ORG_ID,
                code="demo-onboarding",
                name="📚 上手指南(demo)",
                description="新用户上手用 — 操作手册 + 权限模型 + 示例素材",
                minio_bucket=BUCKET,
                visibility="public",
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )
        # folders
        await session.execute(
            insert(Folder)
            .values(
                id=DOC_FOLDER_ID,
                project_id=PROJECT_ID,
                parent_folder_id=None,
                name="01-入门文档",
                minio_prefix="01-入门文档/",
                is_sensitive=False,
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )
        await session.execute(
            insert(Folder)
            .values(
                id=DEMO_FOLDER_ID,
                project_id=PROJECT_ID,
                parent_folder_id=None,
                name="02-示例素材",
                minio_prefix="02-示例素材/",
                is_sensitive=False,
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )
        await session.execute(
            insert(Folder)
            .values(
                id=SENSITIVE_FOLDER_ID,
                project_id=PROJECT_ID,
                parent_folder_id=None,
                name="03-敏感示例",
                minio_prefix="03-敏感示例/",
                is_sensitive=True,
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )
        await session.commit()
    log.info("DB rows upserted")

    # ─── 2) OpenFGA tuples ────────────────────────────────────────────────
    permissions = await create_permissions_service(settings)

    # project → org parent + alice 作为 project admin(高层 helper)
    # tenant_key fallback 到 str(org_id) — 对齐 projects.py:85 logic
    try:
        await permissions.bootstrap_project(
            project_id=str(PROJECT_ID),
            organization_tenant_key=str(ORG_ID),
            creator_open_id=ADMIN_OPEN_ID,
        )
    except Exception as e:  # noqa: BLE001 — tuple 已存在的常见错,可忽略
        log.info("project bootstrap tuples may already exist: %s", e)

    # 普通 folder → project parent
    for fid in (DOC_FOLDER_ID, DEMO_FOLDER_ID):
        try:
            await permissions.bootstrap_folder(
                folder_id=str(fid), parent_type="project", parent_id=str(PROJECT_ID),
            )
        except Exception as e:  # noqa: BLE001
            log.info("folder %s bootstrap: %s", fid, e)

    # sensitive folder → project parent
    try:
        await permissions.bootstrap_sensitive_folder(
            folder_id=str(SENSITIVE_FOLDER_ID), project_id=str(PROJECT_ID),
        )
    except Exception as e:  # noqa: BLE001
        log.info("sensitive folder bootstrap: %s", e)

    # sensitive folder 给 alice invited_downloader(沿用 PR #92 模式,创建者自动可见)
    try:
        await permissions.invite_to_sensitive_folder(
            sensitive_folder_id=str(SENSITIVE_FOLDER_ID),
            subject=f"user:{ADMIN_OPEN_ID}",
            level="downloader",
            duration_seconds=None,
        )
    except Exception as e:  # noqa: BLE001
        log.info("sensitive folder invite alice: %s", e)

    log.info("OpenFGA tuples written")

    # ─── 3) MinIO upload + asset rows + OpenFGA asset bootstrap ───────────
    s3 = boto3.client(
        "s3",
        endpoint_url=settings.minio_endpoint_internal,
        aws_access_key_id=settings.minio_access_key,
        aws_secret_access_key=settings.minio_secret_key,
        config=Config(signature_version="s3v4"),
    )
    try:
        s3.head_bucket(Bucket=BUCKET)
    except ClientError:
        s3.create_bucket(Bucket=BUCKET)

    files = _build_files()
    uploaded: list[str] = []
    async with sm() as session:
        for filename, body, content_type, folder_id in files:
            # MinIO key:用 folder prefix + filename
            folder_row = await session.get(Folder, folder_id)
            if folder_row is None:
                log.warning("folder %s not found, skip %s", folder_id, filename)
                continue
            key = folder_row.minio_prefix + filename
            s3.put_object(Bucket=BUCKET, Key=key, Body=body, ContentType=content_type)
            aid = uuid.uuid5(folder_id, filename)
            await session.execute(
                insert(Asset)
                .values(
                    id=aid,
                    folder_id=folder_id,
                    filename=filename,
                    minio_bucket=BUCKET,
                    minio_key=key,
                    etag=None,
                    size_bytes=len(body),
                    content_type=content_type,
                    uploader_id=ADMIN_USER_ID,
                )
                .on_conflict_do_nothing(index_elements=["id"])
            )
            try:
                await permissions.bootstrap_asset(
                    asset_id=str(aid),
                    parent_type="sensitive_folder" if folder_row.is_sensitive else "folder",
                    parent_id=str(folder_id),
                )
            except Exception as e:  # noqa: BLE001
                log.info("asset %s bootstrap: %s", aid, e)
            uploaded.append(filename)
        await session.commit()

    await permissions.close()

    log.info("DONE — project %s · %d folders · %d assets uploaded",
             PROJECT_ID, 3, len(uploaded))
    print(f"ONBOARDING_PROJECT_ID={PROJECT_ID}")
    print(f"uploaded: {uploaded}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:  # noqa: BLE001
        log.exception("seed_onboarding failed: %s", e)
        sys.exit(1)
