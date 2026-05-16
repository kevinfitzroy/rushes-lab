"""seed demo data — 创建演示用项目/folder(嵌套)/asset + 把飞书登录的真 user 升 org admin。

执行:
  docker exec ms-api python -m scripts.seed_demo_data

行为:
  1. 把 users 表里 open_id != dev_xxx 的真 user 全部 assign org admin
  2. 创建若干 demo projects(覆盖典型业务场景)
  3. **递归创建嵌套 folder 树**(深度可达 5 层,sensitive 子树整链 sensitive)
  4. 每 folder 1-2 个 dummy 文件作 asset(用 boto3 直接 PUT)
  5. idempotent(deterministic uuid5(parent, name) + on_conflict_do_nothing)
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

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


def F(name: str, children: list[dict] | None = None, *, sensitive: bool = False) -> dict:
    """folder tree builder — children 必传 list,sensitive keyword-only。"""
    return {"name": name, "sensitive": sensitive, "children": children or []}


# 5 个 demo projects(每个有深嵌套树)
DEMO_PROJECTS: list[dict[str, Any]] = [
    {
        "id": uuid.UUID("11111111-1111-1111-1111-111111111101"),
        "code": "wedding-2026-spring",
        "name": "2026 春季婚礼策划",
        "description": "春节后档期婚礼现场拍摄 + 后期",
        "bucket": "ms-dev",
        "visibility": "private",
        "folders": [
            F("现场原片", [
                F("无人机", [F("航拍 4K"), F("航拍 1080p")]),
                F("全景", [F("室内"), F("室外")]),
                F("特写", [
                    F("新人", [F("交换戒指"), F("拥抱")]),
                    F("宾客", [F("家属"), F("朋友团")]),
                ]),
                F("花絮"),
            ]),
            F("成片", [
                F("导演剪辑", [F("初剪"), F("精修"), F("终版")]),
                F("社交媒体", [F("微博 1080x1080"), F("小红书"), F("抖音 9-16")]),
            ]),
            F("客户私密照 (VIP)", [
                F("敬酒", sensitive=True),
                F("婚房", sensitive=True),
                F("家庭合影", [
                    F("长辈", sensitive=True),
                    F("孩童", sensitive=True),
                ], sensitive=True),
            ], sensitive=True),
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
            F("术前照", [
                F("正面", sensitive=True),
                F("侧面", [
                    F("左 45 度", sensitive=True),
                    F("右 45 度", sensitive=True),
                ], sensitive=True),
                F("特写", [
                    F("眼周", sensitive=True),
                    F("法令纹", sensitive=True),
                    F("颈纹", sensitive=True),
                ], sensitive=True),
            ], sensitive=True),
            F("术中记录", [
                F("第 1 次", sensitive=True),
                F("第 2 次", sensitive=True),
                F("第 3 次", sensitive=True),
                F("第 4 次", sensitive=True),
            ], sensitive=True),
            F("术后跟拍", [F("一周"), F("一月"), F("三月")]),
            F("成品推广素材", [
                F("对比图"),
                F("视频剪辑", [F("15s"), F("30s"), F("60s")]),
            ]),
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
            F("现场视频", [
                F("主舞台", [F("致辞"), F("产品展示"), F("互动 Q&A")]),
                F("分会场", [
                    F("VIP 区"),
                    F("媒体区"),
                    F("展台", [F("展位 A"), F("展位 B"), F("展位 C")]),
                ]),
            ]),
            F("精选照片", [F("人物"), F("产品细节"), F("场景氛围")]),
            F("内部花絮", [
                F("彩排", sensitive=True),
                F("后台", sensitive=True),
            ], sensitive=True),
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
            F("操作示范", [
                F("基础", [F("无菌操作"), F("仪器开关")]),
                F("进阶", [F("分层注射"), F("能量参数设置")]),
                F("高级", [F("综合面诊"), F("方案设计")]),
            ]),
            F("典型案例", [
                F("成功案例", [
                    F("年龄分布", [F("25-35"), F("35-45"), F("45+")]),
                ]),
                F("失败教训", [F("流程问题"), F("沟通问题")]),
            ]),
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
            F("咨询录像", [
                F("第 1 次", sensitive=True),
                F("第 2 次", sensitive=True),
                F("第 3 次", sensitive=True),
            ], sensitive=True),
            F("方案文档", [
                F("初稿", sensitive=True),
                F("终稿", [
                    F("中文", sensitive=True),
                    F("英文", sensitive=True),
                ], sensitive=True),
            ], sensitive=True),
        ],
    },
]


def _folder_id(parent_uuid: uuid.UUID, name: str) -> uuid.UUID:
    """deterministic uuid5(parent, name)— idempotent。"""
    return uuid.uuid5(parent_uuid, name)


def _asset_id(folder_uuid: uuid.UUID, filename: str) -> uuid.UUID:
    return uuid.uuid5(folder_uuid, filename)


def _flatten(tree: list[dict], parent_uuid: uuid.UUID, parent_prefix: str,
             parent_type: str, parent_is_sensitive: bool,
             out: list[dict]) -> None:
    """递归把 folder tree 展平为 list,带计算后的 minio_prefix + parent info。"""
    for node in tree:
        fid = _folder_id(parent_uuid, node["name"])
        prefix = parent_prefix + node["name"] + "/"
        is_sensitive = node["sensitive"] or parent_is_sensitive
        # 注:DB 字段 parent_folder_id 仅在 parent 是 folder/sensitive_folder 时有值
        db_parent_folder_id = parent_uuid if parent_type in ("folder", "sensitive_folder") else None
        out.append({
            "id": fid,
            "name": node["name"],
            "is_sensitive": is_sensitive,
            "minio_prefix": prefix,
            "db_parent_folder_id": db_parent_folder_id,
            "fga_parent_type": parent_type,
            "fga_parent_id": parent_uuid,
        })
        self_type = "sensitive_folder" if is_sensitive else "folder"
        _flatten(node["children"], fid, prefix, self_type, is_sensitive, out)


async def main() -> None:
    settings = get_settings()
    sm = get_sessionmaker()
    permissions = await create_permissions_service(settings)

    # ─── 1) 真 user 升 org admin ───
    async with sm() as session:
        # idempotent organization upsert(防 ORG_ID 未存在)
        await session.execute(
            insert(Organization)
            .values(id=ORG_ID, name="dev-clinic", feishu_tenant_key=None)
            .on_conflict_do_nothing(index_elements=["id"])
        )
        await session.commit()

        res = await session.execute(
            select(User).where(~User.feishu_open_id.like("dev_%"))
        )
        real_users = list(res.scalars())

    for u in real_users:
        try:
            await permissions.assign_user_to_organization(
                user_id=str(u.id), organization_id=str(ORG_ID), role="admin")
            log.info("升 admin:user=%s (%s)", u.name, str(u.id)[:8])
        except Exception as e:
            log.debug("admin tuple exists: %s", e)

    # ─── 2) projects + 递归 folder 树 ─────────────────────────────────
    total_folders = 0
    total_assets = 0

    async with sm() as session:
        for proj in DEMO_PROJECTS:
            await session.execute(
                insert(Project).values(
                    id=proj["id"], organization_id=ORG_ID,
                    code=proj["code"], name=proj["name"],
                    description=proj["description"],
                    minio_bucket=proj["bucket"], visibility=proj["visibility"],
                ).on_conflict_do_nothing(index_elements=["id"])
            )

            # flatten tree
            flat: list[dict] = []
            _flatten(proj["folders"], proj["id"], f"{proj['code']}/",
                     "project", False, flat)

            # DB insert all folders
            for f in flat:
                await session.execute(
                    insert(Folder).values(
                        id=f["id"], project_id=proj["id"],
                        parent_folder_id=f["db_parent_folder_id"],
                        name=f["name"], minio_prefix=f["minio_prefix"],
                        is_sensitive=f["is_sensitive"],
                    ).on_conflict_do_nothing(index_elements=["id"])
                )
            total_folders += len(flat)

            proj["_flat"] = flat  # 留给后续 OpenFGA + asset
        await session.commit()
    log.info("DB rows inserted — %d folders total", total_folders)

    # ─── 3) OpenFGA tuples(每 folder bootstrap parent 关系)──────────────
    for proj in DEMO_PROJECTS:
        try:
            await permissions.bootstrap_project(
                project_id=str(proj["id"]), organization_id=str(ORG_ID))
        except Exception as e:
            log.debug("project tuple exists: %s", e)

        for f in proj["_flat"]:
            try:
                await permissions.bootstrap_folder(
                    folder_id=str(f["id"]),
                    parent_type=f["fga_parent_type"],
                    parent_id=str(f["fga_parent_id"]),
                    is_sensitive=f["is_sensitive"],
                )
            except Exception as e:
                log.debug("folder tuple exists: %s", e)
    log.info("OpenFGA tuples written")

    # ─── 4) demo asset 文件(boto3 直传)— 每 folder 1 个,叶子加到 2 ──
    s3 = boto3.client(
        "s3",
        endpoint_url=settings.minio_endpoint_internal,
        aws_access_key_id=settings.minio_access_key,
        aws_secret_access_key=settings.minio_secret_key,
        config=Config(signature_version="s3v4"),
    )
    try:
        s3.head_bucket(Bucket="ms-dev")
    except ClientError:
        s3.create_bucket(Bucket="ms-dev")

    # 区分叶子:在 flat 内 id 没人作 parent 的就是叶子
    async with sm() as session:
        for proj in DEMO_PROJECTS:
            flat = proj["_flat"]
            parent_ids = {f["fga_parent_id"] for f in flat if f["fga_parent_type"] in ("folder", "sensitive_folder")}
            for f in flat:
                is_leaf = f["id"] not in parent_ids
                count = 2 if is_leaf else 1
                for i in range(1, count + 1):
                    filename = f"demo-{i:02d}.txt"
                    key = f["minio_prefix"] + filename
                    body = (f"demo {i}/{count} for {proj['code']}/{f['name']}\n"
                            f"--- 演示文件,可下载验证 ---\n").encode()
                    s3.put_object(Bucket="ms-dev", Key=key, Body=body,
                                  ContentType="text/plain")
                    aid = _asset_id(f["id"], filename)
                    await session.execute(
                        insert(Asset).values(
                            id=aid, folder_id=f["id"], filename=filename,
                            minio_bucket="ms-dev", minio_key=key,
                            etag=None, size_bytes=len(body),
                            content_type="text/plain", uploader_id=None,
                        ).on_conflict_do_nothing(index_elements=["id"])
                    )
                    try:
                        await permissions.bootstrap_asset(
                            asset_id=str(aid),
                            parent_folder_id=str(f["id"]),
                            parent_is_sensitive=f["is_sensitive"],
                        )
                    except Exception:
                        pass
                    total_assets += 1
        await session.commit()
    log.info("uploaded + indexed %d demo assets", total_assets)

    await permissions.close()
    log.info("DONE — %d projects · %d folders · %d assets",
             len(DEMO_PROJECTS), total_folders, total_assets)


if __name__ == "__main__":
    asyncio.run(main())
