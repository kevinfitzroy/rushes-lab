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
  - OpenFGA tuples:
      alice → organization admin (→ project admin → 所有 folder admin)
      bob   → project member (→ 普通 folder can_view/can_edit/can_download)
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
ORG_ID = uuid.UUID("00000000-0000-0000-0000-00000000a001")
ADMIN_USER_ID = uuid.UUID("00000000-0000-0000-0000-00000000u001")
MEMBER_USER_ID = uuid.UUID("00000000-0000-0000-0000-00000000u002")
PROJECT_ID = uuid.UUID("00000000-0000-0000-0000-00000000p001")
NORMAL_FOLDER_ID = uuid.UUID("00000000-0000-0000-0000-00000000f001")
SENSITIVE_FOLDER_ID = uuid.UUID("00000000-0000-0000-0000-00000000f002")

BUCKET = "ms-dev"


async def main() -> None:
    settings = get_settings()
    sm = get_sessionmaker()

    # ─── 1) DB upsert ─────────────────────────────────────────────────────
    async with sm() as session:
        # organization
        await session.execute(
            insert(Organization)
            .values(id=ORG_ID, name="dev-clinic", feishu_tenant_key=None)
            .on_conflict_do_nothing(index_elements=["id"])
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

    # ─── 2) OpenFGA tuples ────────────────────────────────────────────────
    permissions = await create_permissions_service(settings)

    # alice → org admin
    await permissions.assign_user_to_organization(
        user_id=str(ADMIN_USER_ID), organization_id=str(ORG_ID), role="admin"
    )

    # project → organization
    await permissions.bootstrap_project(
        project_id=str(PROJECT_ID), organization_id=str(ORG_ID)
    )

    # bob → project member (直接 user grant,不走 group)
    from openfga_sdk.client.models import ClientTuple, ClientWriteRequest
    await permissions._client.write(  # type: ignore[attr-defined]
        ClientWriteRequest(
            writes=[
                ClientTuple(
                    user=f"user:{MEMBER_USER_ID}",
                    relation="editor",
                    object=f"project:{PROJECT_ID}",
                )
            ]
        )
    )

    # folders bootstrap
    await permissions.bootstrap_folder(
        folder_id=str(NORMAL_FOLDER_ID),
        parent_type="project",
        parent_id=str(PROJECT_ID),
        is_sensitive=False,
    )
    await permissions.bootstrap_folder(
        folder_id=str(SENSITIVE_FOLDER_ID),
        parent_type="project",
        parent_id=str(PROJECT_ID),
        is_sensitive=True,
    )
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
