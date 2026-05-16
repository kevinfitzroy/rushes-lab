"""seed demo data — 创建演示用项目/folder/asset + 把飞书登录的真 user 升 org admin。

执行:
  docker exec ms-api python -m scripts.seed_demo_data

行为:
  1. 把 users 表里 open_id != dev_xxx 的真 user 全部 assign org admin(可见所有 project + folder)
  2. 创建 5 个 demo projects(各种业务场景)
  3. 每 project 2-4 folders(2 普通 + 1 sensitive)
  4. 每 folder 2-3 个 dummy txt 文件作 asset(用 boto3 直接 PUT)
  5. idempotent — 重跑不重复
"""
from __future__ import annotations

import asyncio
import io
import logging
import uuid

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.db.session import get_sessionmaker
from app.db.tables import Asset, Folder, Organization, Project, User
from app.services.permissions import create_permissions_service
from app.settings import get_settings

logging.basicConfig(level=logging.INFO, format="%(levelname)s — %(message)s")
log = logging.getLogger("seed")

ORG_ID = uuid.UUID("00000000-0000-0000-0000-0000000000a1")

# 5 个 demo projects(覆盖典型业务场景)
DEMO_PROJECTS = [
    {
        "id": uuid.UUID("11111111-1111-1111-1111-111111111101"),
        "code": "wedding-2026-spring",
        "name": "2026 春季婚礼策划",
        "description": "春节后档期婚礼现场拍摄 + 后期",
        "bucket": "ms-dev",
        "visibility": "private",
        "folders": [
            ("现场原片", False),
            ("成片", False),
            ("客户私密照(VIP)", True),
        ],
    },
    {
        "id": uuid.UUID("11111111-1111-1111-1111-111111111102"),
        "code": "client-zhang-skincare",
        "name": "张女士抗衰疗程",
        "description": "8 次疗程对比纪录,3 个月跟拍",
        "bucket": "ms-dev",
        "visibility": "private",
        "folders": [
            ("术前照", True),
            ("术中记录", True),
            ("术后跟拍", False),
            ("成品推广素材", False),
        ],
    },
    {
        "id": uuid.UUID("11111111-1111-1111-1111-111111111103"),
        "code": "brand-event-2026-q2",
        "name": "Q2 品牌发布会",
        "description": "新品发布会现场 + 媒体素材",
        "bucket": "ms-dev",
        "visibility": "public",
        "folders": [
            ("现场视频", False),
            ("精选照片", False),
            ("内部花絮", True),
        ],
    },
    {
        "id": uuid.UUID("11111111-1111-1111-1111-111111111104"),
        "code": "training-2026",
        "name": "内部培训素材库",
        "description": "案例教学,新员工 onboarding",
        "bucket": "ms-dev",
        "visibility": "public",
        "folders": [
            ("操作示范", False),
            ("典型案例", False),
        ],
    },
    {
        "id": uuid.UUID("11111111-1111-1111-1111-111111111105"),
        "code": "client-li-private",
        "name": "李先生私域(机密)",
        "description": "高净值客户全程私密咨询",
        "bucket": "ms-dev",
        "visibility": "stealth",
        "folders": [
            ("咨询录像", True),
            ("方案文档", True),
        ],
    },
]


def _folder_id(project_id: uuid.UUID, name: str) -> uuid.UUID:
    """deterministic folder UUID per project + name(idempotent)。"""
    return uuid.uuid5(project_id, name)


def _asset_id(folder_id: uuid.UUID, filename: str) -> uuid.UUID:
    return uuid.uuid5(folder_id, filename)


async def main() -> None:
    settings = get_settings()
    sm = get_sessionmaker()
    permissions = await create_permissions_service(settings)

    # ─── 1) 真 user 升 org admin ───────────────────────────────────────────
    async with sm() as session:
        res = await session.execute(
            select(User).where(~User.feishu_open_id.like("dev_%"))
        )
        real_users = list(res.scalars())

    if not real_users:
        log.warning("没找到真飞书 user(只有 dev_admin/dev_member);先在飞书登录一次再跑")
    for u in real_users:
        await permissions.assign_user_to_organization(
            user_id=str(u.id), organization_id=str(ORG_ID), role="admin"
        )
        log.info("升 admin:user=%s (%s)", u.name, str(u.id)[:8])

    # ─── 2) projects + folders ────────────────────────────────────────────
    async with sm() as session:
        for proj in DEMO_PROJECTS:
            await session.execute(
                insert(Project)
                .values(
                    id=proj["id"], organization_id=ORG_ID,
                    code=proj["code"], name=proj["name"],
                    description=proj["description"],
                    minio_bucket=proj["bucket"], visibility=proj["visibility"],
                )
                .on_conflict_do_nothing(index_elements=["id"])
            )
            for folder_name, is_sensitive in proj["folders"]:
                fid = _folder_id(proj["id"], folder_name)
                prefix = f"{proj['code']}/{folder_name}/"
                await session.execute(
                    insert(Folder)
                    .values(
                        id=fid, project_id=proj["id"], parent_folder_id=None,
                        name=folder_name, minio_prefix=prefix,
                        is_sensitive=is_sensitive,
                    )
                    .on_conflict_do_nothing(index_elements=["id"])
                )
        await session.commit()
    log.info("DB rows inserted")

    # ─── 3) OpenFGA tuples ───────────────────────────────────────────────
    for proj in DEMO_PROJECTS:
        try:
            await permissions.bootstrap_project(
                project_id=str(proj["id"]), organization_id=str(ORG_ID)
            )
        except Exception as e:
            log.debug("project tuple exists: %s", e)

        for folder_name, is_sensitive in proj["folders"]:
            fid = _folder_id(proj["id"], folder_name)
            try:
                await permissions.bootstrap_folder(
                    folder_id=str(fid),
                    parent_type="project",
                    parent_id=str(proj["id"]),
                    is_sensitive=is_sensitive,
                )
            except Exception as e:
                log.debug("folder tuple exists: %s", e)
    log.info("OpenFGA tuples written")

    # ─── 4) demo asset 文件(boto3 直传)──────────────────────────────────
    s3 = boto3.client(
        "s3",
        endpoint_url=settings.minio_endpoint_internal,
        aws_access_key_id=settings.minio_access_key,
        aws_secret_access_key=settings.minio_secret_key,
        config=Config(signature_version="s3v4"),
    )

    # bucket idempotent
    try:
        s3.head_bucket(Bucket="ms-dev")
    except ClientError:
        s3.create_bucket(Bucket="ms-dev")

    asset_count = 0
    async with sm() as session:
        for proj in DEMO_PROJECTS:
            for folder_name, _ in proj["folders"]:
                fid = _folder_id(proj["id"], folder_name)
                prefix = f"{proj['code']}/{folder_name}/"
                for i in range(1, 3):  # 2 个 demo file per folder
                    filename = f"demo-{i:02d}.txt"
                    key = f"{prefix}{filename}"
                    body = (f"demo file {i} for {proj['code']}/{folder_name}\n"
                            f"--- 演示文件,可下载查看 ---\n").encode()
                    s3.put_object(Bucket="ms-dev", Key=key, Body=body,
                                  ContentType="text/plain")
                    aid = _asset_id(fid, filename)
                    await session.execute(
                        insert(Asset)
                        .values(
                            id=aid, folder_id=fid, filename=filename,
                            minio_bucket="ms-dev", minio_key=key,
                            etag=None, size_bytes=len(body),
                            content_type="text/plain", uploader_id=None,
                        )
                        .on_conflict_do_nothing(index_elements=["id"])
                    )
                    try:
                        await permissions.bootstrap_asset(
                            asset_id=str(aid), parent_folder_id=str(fid),
                            parent_is_sensitive=False,  # parent type 由 folder.is_sensitive 决定
                        )
                    except Exception:
                        pass
                    asset_count += 1
        await session.commit()
    log.info("uploaded + indexed %d demo assets", asset_count)

    # 修 parent_is_sensitive — bootstrap_asset 在 v3 model 下要按 folder type;
    # 上面统一传 False 会导致 sensitive folder 下的 asset parent type 错;
    # 单独重写 sensitive folder 下的 asset tuple
    from openfga_sdk.client.models import ClientTuple, ClientWriteRequest
    fix_writes = []
    fix_deletes = []
    for proj in DEMO_PROJECTS:
        for folder_name, is_sensitive in proj["folders"]:
            if not is_sensitive:
                continue
            fid = _folder_id(proj["id"], folder_name)
            for i in range(1, 3):
                aid = _asset_id(fid, f"demo-{i:02d}.txt")
                fix_deletes.append(ClientTuple(
                    user=f"folder:{fid}", relation="parent", object=f"asset:{aid}"
                ))
                fix_writes.append(ClientTuple(
                    user=f"sensitive_folder:{fid}", relation="parent", object=f"asset:{aid}"
                ))
    if fix_writes:
        try:
            await permissions._client.write(ClientWriteRequest(deletes=fix_deletes))  # type: ignore[attr-defined]
        except Exception as e:
            log.debug("delete-fix tolerated: %s", e)
        try:
            await permissions._client.write(ClientWriteRequest(writes=fix_writes))  # type: ignore[attr-defined]
        except Exception as e:
            log.debug("write-fix tolerated: %s", e)
        log.info("sensitive folder asset parent tuples fixed: %d", len(fix_writes))

    await permissions.close()
    log.info("DONE — 真 user %d 个升 admin;%d 项目;%d assets",
             len(real_users), len(DEMO_PROJECTS), asset_count)


if __name__ == "__main__":
    asyncio.run(main())
