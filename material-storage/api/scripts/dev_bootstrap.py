"""dev bootstrap — 创建测试数据用于 e2e 测试(无飞书 OIDC 依赖)。

执行:
  docker compose exec ms-api python -m scripts.dev_bootstrap

输出:
  ADMIN_USER_ID=...
  MEMBER_USER_ID=...
  ORG_ID=...
  PROJECT_ID=...
  NORMAL_FOLDER_ID=...
  SENSITIVE_FOLDER_ID=...
  BUCKET=...

行为:
  - org / project / folders / users 用固定 UUID(idempotent re-runs OK)
  - OpenFGA tuples(v4 三轴 + #148 UUID subject):
      alice → organization admin (→ project admin → 所有 folder admin)
      bob   → project viewer/downloader/uploader(→ 普通 folder 可看/可下/可传)
              bob NOT invited to sensitive folder(测试用)
  - MinIO bucket 创建(boto3 head_bucket → create_bucket)
"""
from __future__ import annotations

import asyncio
import logging
import sys
import uuid

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from sqlalchemy.dialects.postgresql import insert

from app.db.session import get_sessionmaker
from app.db.tables import Folder, Organization, Project, User
from app.services.permissions import create_permissions_service
from app.settings import get_settings

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s — %(message)s")
log = logging.getLogger("bootstrap")

# 固定 UUIDs(idempotent)
ORG_ID = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
ADMIN_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
MEMBER_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")
PROJECT_ID = uuid.UUID("00000000-0000-0000-0000-0000000000b1")
NORMAL_FOLDER_ID = uuid.UUID("00000000-0000-0000-0000-0000000000c1")
SENSITIVE_FOLDER_ID = uuid.UUID("00000000-0000-0000-0000-0000000000c2")

BUCKET = "ms-dev"

# OpenFGA organization subject 的 tenant_key(#148 起 org tuple 用它拼;
# 与 seed_demo_data.py 对齐;get_default_organization 取 feishu_tenant_key or str(org_id))
TENANT_KEY = "dev_tenant_001"


async def main() -> None:
    settings = get_settings()
    sm = get_sessionmaker()

    # ─── 1) DB upsert ─────────────────────────────────────────────────────
    async with sm() as session:
        # organization(tenant_key 与 seed_demo_data 一致,OpenFGA org subject 用它)
        await session.execute(
            insert(Organization)
            .values(id=ORG_ID, name="dev-clinic", feishu_tenant_key=TENANT_KEY)
            .on_conflict_do_update(
                index_elements=["id"],
                set_={"feishu_tenant_key": TENANT_KEY, "name": "dev-clinic"},
            )
        )
        # users
        await session.execute(
            insert(User)
            .values(
                id=ADMIN_USER_ID,
                feishu_open_id="dev_admin_open_id",
                name="alice (admin)",
                email="alice@dev.local",
                is_active=True,
                organization_id=ORG_ID,
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )
        await session.execute(
            insert(User)
            .values(
                id=MEMBER_USER_ID,
                feishu_open_id="dev_member_open_id",
                name="bob (member)",
                email="bob@dev.local",
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
                code="proj-dev-001",
                name="Dev Test Project",
                description="e2e 测试项目",
                minio_bucket=BUCKET,
                visibility="private",
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )
        # folders
        await session.execute(
            insert(Folder)
            .values(
                id=NORMAL_FOLDER_ID,
                project_id=PROJECT_ID,
                parent_folder_id=None,
                name="raw",
                minio_prefix="raw/",
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
                name="vip-secret",
                minio_prefix="vip-secret/",
                is_sensitive=True,
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )
        await session.commit()

    log.info("DB rows inserted (or already exist)")

    # ─── 2) OpenFGA tuples(#148 起 subject = user:<users.id UUID>)──────────
    permissions = await create_permissions_service(settings)

    # alice → org admin(#148 起 org subject = organization:<tenant_key>)
    from openfga_sdk.client.models import ClientTuple, ClientWriteRequest
    # 每个 write 独立 try/except — 重复 bootstrap 时 tuple 已存在(OpenFGA write
    # 非幂等,400 already exists),与 seed_onboarding_project.py 同款约定:log 后继续
    try:
        await permissions._client.write(
            ClientWriteRequest(
                writes=[
                    ClientTuple(
                        user=f"user:{ADMIN_USER_ID}",
                        relation="admin",
                        object=f"organization:{TENANT_KEY}",
                    )
                ]
            )
        )
    except Exception as e:
        log.info("org admin tuple already exists: %s", e)

    try:
        await permissions.add_user_to_organization(
            organization_tenant_key=TENANT_KEY, user_id=str(ADMIN_USER_ID)
        )
    except Exception as e:
        log.info("org member tuple already exists: %s", e)

    # project → organization + alice project admin(#148 签名:
    # organization_tenant_key + creator_user_id)
    try:
        await permissions.bootstrap_project(
            project_id=str(PROJECT_ID),
            organization_tenant_key=TENANT_KEY,
            creator_user_id=str(ADMIN_USER_ID),
        )
    except Exception as e:
        log.info("project bootstrap tuples already exists: %s", e)

    # bob → project 三轴并列(viewer/downloader/uploader;v3 的 editor 关系
    # 已从 model 移除,#69 stale 根因之一;S7 上传 / S9 下载分别要 uploader/downloader)
    for role in ("viewer", "downloader", "uploader"):
        try:
            await permissions.add_project_subject(
                project_id=str(PROJECT_ID),
                subject=f"user:{MEMBER_USER_ID}",
                role=role,
            )
        except Exception as e:
            log.info("bob project %s tuple already exists: %s", role, e)

    # folders bootstrap(#148 起:普通 folder 用 bootstrap_folder;sensitive 用
    # bootstrap_sensitive_folder — 旧 is_sensitive 参数已移除,是 #69 深层 stale 之一)
    try:
        await permissions.bootstrap_folder(
            folder_id=str(NORMAL_FOLDER_ID),
            parent_type="project",
            parent_id=str(PROJECT_ID),
        )
    except Exception as e:
        log.info("normal folder parent tuple already exists: %s", e)

    try:
        await permissions.bootstrap_sensitive_folder(
            folder_id=str(SENSITIVE_FOLDER_ID),
            project_id=str(PROJECT_ID),
        )
    except Exception as e:
        log.info("sensitive folder parent tuple already exists: %s", e)
    # NOTE: bob NOT invited to sensitive folder — 测试时 alice 用 /folders/{id}/invite 邀请

    await permissions.close()
    log.info("OpenFGA tuples written")

    # ─── 3) MinIO bucket create(idempotent)─────────────────────────────
    s3 = boto3.client(
        "s3",
        endpoint_url=settings.minio_endpoint_internal,
        aws_access_key_id=settings.minio_access_key,
        aws_secret_access_key=settings.minio_secret_key,
        config=Config(signature_version="s3v4"),
    )
    try:
        s3.head_bucket(Bucket=BUCKET)
        log.info("bucket %s exists", BUCKET)
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchBucket"):
            s3.create_bucket(Bucket=BUCKET)
            log.info("bucket %s created", BUCKET)
        else:
            raise

    # ─── 4) Output for shell consumption ───────────────────────────────────
    print("---BOOTSTRAP RESULT---", file=sys.stderr)
    print(f"ADMIN_USER_ID={ADMIN_USER_ID}")
    print(f"MEMBER_USER_ID={MEMBER_USER_ID}")
    print(f"ORG_ID={ORG_ID}")
    print(f"PROJECT_ID={PROJECT_ID}")
    print(f"NORMAL_FOLDER_ID={NORMAL_FOLDER_ID}")
    print(f"SENSITIVE_FOLDER_ID={SENSITIVE_FOLDER_ID}")
    print(f"BUCKET={BUCKET}")


if __name__ == "__main__":
    asyncio.run(main())
