"""seed demo data — iter a1(v4 model + 飞书 ID 直作 OpenFGA subject)。

执行:
  docker exec ms-api python -m scripts.seed_demo_data

行为(idempotent;重复跑无副作用):
  1. upsert organization(含 feishu_tenant_key)+ 几个模拟 department / group
  2. 升所有真飞书 user(open_id 不以 dev_ 开头)为 org admin
  3. 创建 demo projects + 一级 folder(普通 + sensitive)+ 二级普通 folder
  4. 写 OpenFGA tuples(bootstrap_project / bootstrap_folder / bootstrap_sensitive_folder)
  5. 配 demo 默认权限:
     - org member → project viewer
     - group:剪辑师 → project downloader
     - 创建者(Evan)→ project admin
  6. 每 folder 1-2 个 dummy 文件(boto3 PUT),bootstrap_asset
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
from app.services.permissions import create_permissions_service, fmt_subject
from app.settings import get_settings

logging.basicConfig(level=logging.INFO, format="%(levelname)s — %(message)s")
log = logging.getLogger("seed")

ORG_ID = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
# v4 model:OpenFGA subject 用飞书 ID;PoC 假数据用 stable 的 dev 字符串
TENANT_KEY = "dev_tenant_001"
DEPT_EDITING = "dep_editing"        # 部门:剪辑组
DEPT_MOTION = "dep_motion_design"   # 子部门:动效设计(挂在 editing 下)
GRP_EDITORS = "grp_editors"          # 用户组:剪辑师

# Folder tree builder
def F(name: str, children: list[dict] | None = None, *, sensitive: bool = False) -> dict:
    return {"name": name, "sensitive": sensitive, "children": children or []}


# v4 限制:sensitive folder 必须直挂 project;sensitive 下不能再嵌套 folder
# 因此 demo 树:
#   - 普通 folder 可以多层嵌套
#   - sensitive folder 平铺在 project 根下,无子目录
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
                F("特写"),
                F("花絮"),
            ]),
            F("成片", [
                F("导演剪辑", [F("初剪"), F("精修"), F("终版")]),
                F("社交媒体", [F("微博"), F("小红书"), F("抖音")]),
            ]),
            F("客户私密照(VIP)", sensitive=True),
            F("家庭合影(VIP)", sensitive=True),
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
            F("术后跟拍", [F("一周"), F("一月"), F("三月")]),
            F("成品推广素材", [F("对比图"), F("视频剪辑")]),
            F("术前照(隐私)", sensitive=True),
            F("术中记录(隐私)", sensitive=True),
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
                F("主舞台"),
                F("分会场", [F("VIP 区"), F("媒体区"), F("展台")]),
            ]),
            F("精选照片", [F("人物"), F("产品细节"), F("场景氛围")]),
            F("内部花絮(机密)", sensitive=True),
        ],
    },
]


def _folder_uuid(parent_uuid: uuid.UUID, name: str) -> uuid.UUID:
    return uuid.uuid5(parent_uuid, name)


def _asset_uuid(folder_uuid: uuid.UUID, filename: str) -> uuid.UUID:
    return uuid.uuid5(folder_uuid, filename)


def _flatten(
    tree: list[dict], parent_uuid: uuid.UUID, parent_prefix: str,
    parent_kind: str,  # "project" | "folder"
    out: list[dict],
) -> None:
    """递归把 folder tree 展平,标注 fga parent type。

    v4 enforce:sensitive folder 直挂 project,且 sensitive 下不再嵌套(本 seed 保证)。
    """
    for node in tree:
        fid = _folder_uuid(parent_uuid, node["name"])
        prefix = parent_prefix + node["name"] + "/"
        is_sensitive = node["sensitive"]
        # parent_folder_id:仅 parent 是 folder 时有值
        db_parent_folder_id = parent_uuid if parent_kind == "folder" else None
        out.append({
            "id": fid,
            "name": node["name"],
            "is_sensitive": is_sensitive,
            "minio_prefix": prefix,
            "db_parent_folder_id": db_parent_folder_id,
            "parent_kind": parent_kind,
            "parent_uuid": parent_uuid,
        })
        # 普通 folder 才递归;sensitive 不再嵌套(v4 限制)
        if not is_sensitive:
            _flatten(node["children"], fid, prefix, "folder", out)


async def main() -> None:
    settings = get_settings()
    sm = get_sessionmaker()
    permissions = await create_permissions_service(settings)

    # ─── 1) Organization upsert(含 feishu_tenant_key) ─────────────────────
    async with sm() as session:
        await session.execute(
            insert(Organization)
            .values(id=ORG_ID, name="dev-clinic", feishu_tenant_key=TENANT_KEY)
            .on_conflict_do_update(
                index_elements=["id"],
                set_={"feishu_tenant_key": TENANT_KEY, "name": "dev-clinic"},
            )
        )
        await session.commit()

        # 真飞书 user 列表
        res = await session.execute(
            select(User).where(~User.feishu_open_id.like("dev_%"))
        )
        real_users = list(res.scalars())

    # ─── 2) 升真 user 为 org admin + 加入 org member + 加入 editing 部门 + editors group ─
    if not real_users:
        log.warning("没有真飞书 user — 跳过 org admin 升级。先访问 web 用飞书 OIDC 登录一次")
    for u in real_users:
        try:
            # org admin(管整个企业 — PoC 简化,只第一个 user 设 admin)
            from openfga_sdk.client.models import ClientTuple, ClientWriteRequest
            await permissions._client.write(
                ClientWriteRequest(writes=[
                    ClientTuple(user=f"user:{u.feishu_open_id}", relation="admin",
                                object=f"organization:{TENANT_KEY}"),
                ])
            )
        except Exception as e:
            log.debug("org admin tuple exists: %s", e)
        # org member
        await permissions.add_user_to_organization(
            organization_tenant_key=TENANT_KEY, user_open_id=u.feishu_open_id
        )
        # editing 部门(模拟,真飞书事件同步在 a2 iter 接)
        await permissions.add_user_to_department(
            department_id=DEPT_EDITING, user_open_id=u.feishu_open_id
        )
        # editors group
        await permissions.add_user_to_group(
            group_id=GRP_EDITORS, user_open_id=u.feishu_open_id
        )
        log.info("升 admin + 部门/组:%s (%s)", u.name, u.feishu_open_id[:12])

    # 模拟部门嵌套:motion_design 是 editing 子部门
    try:
        await permissions.add_department_as_subdept(
            parent_department_id=DEPT_EDITING, child_department_id=DEPT_MOTION
        )
    except Exception:
        pass

    # ─── 3) projects + folder 树 ─────────────────────────────────────────────
    total_folders = total_assets = 0
    flat_by_proj: dict[uuid.UUID, list[dict]] = {}

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

            flat: list[dict] = []
            _flatten(proj["folders"], proj["id"], f"{proj['code']}/", "project", flat)

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
            flat_by_proj[proj["id"]] = flat
        await session.commit()
    log.info("DB:%d folders", total_folders)

    # ─── 4) OpenFGA bootstrap + 默认权限 ────────────────────────────────────
    creator_open_id = real_users[0].feishu_open_id if real_users else None

    for proj in DEMO_PROJECTS:
        # bootstrap_project:org parent + creator admin(creator 兜底:tenant 本身)
        if creator_open_id:
            try:
                await permissions.bootstrap_project(
                    project_id=str(proj["id"]),
                    organization_tenant_key=TENANT_KEY,
                    creator_open_id=creator_open_id,
                )
            except Exception as e:
                log.debug("bootstrap_project exists: %s", e)

        # 默认权限:editing 部门(模拟"全员/默认查看")→ viewer
        # 真生产中:用飞书根部门 id 表示全员;PoC 用 editing 部门即可
        try:
            await permissions.add_project_subject(
                project_id=str(proj["id"]),
                subject=fmt_subject("department", DEPT_EDITING),
                role="viewer",
            )
        except Exception:
            pass
        # 部门 editing → uploader(剪辑组可以上传)
        try:
            await permissions.add_project_subject(
                project_id=str(proj["id"]),
                subject=fmt_subject("department", DEPT_EDITING),
                role="uploader",
            )
        except Exception:
            pass
        # group editors → downloader
        try:
            await permissions.add_project_subject(
                project_id=str(proj["id"]),
                subject=fmt_subject("group", GRP_EDITORS),
                role="downloader",
            )
        except Exception:
            pass

        # folder bootstrap
        for f in flat_by_proj[proj["id"]]:
            try:
                if f["is_sensitive"]:
                    # sensitive 必直挂 project(v4 enforce + flatten 已保证)
                    await permissions.bootstrap_sensitive_folder(
                        folder_id=str(f["id"]), project_id=str(proj["id"]),
                    )
                else:
                    await permissions.bootstrap_folder(
                        folder_id=str(f["id"]),
                        parent_type=f["parent_kind"],  # type: ignore[arg-type]
                        parent_id=str(f["parent_uuid"]),
                    )
            except Exception as e:
                log.debug("folder tuple exists: %s", e)

        # 给创建者 sensitive folder 邀请 viewer(否则连看都看不见)
        if creator_open_id:
            for f in flat_by_proj[proj["id"]]:
                if f["is_sensitive"]:
                    try:
                        await permissions.invite_to_sensitive_folder(
                            sensitive_folder_id=str(f["id"]),
                            subject=f"user:{creator_open_id}",
                            level="downloader",
                        )
                    except Exception:
                        pass

    log.info("OpenFGA tuples 写入完成")

    # ─── 5) demo asset 文件 ─────────────────────────────────────────────────
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

    async with sm() as session:
        for proj in DEMO_PROJECTS:
            flat = flat_by_proj[proj["id"]]
            parent_ids = {
                f["parent_uuid"] for f in flat if f["parent_kind"] == "folder"
            }
            for f in flat:
                is_leaf = f["id"] not in parent_ids
                count = 2 if is_leaf else 1
                for i in range(1, count + 1):
                    filename = f"demo-{i:02d}.txt"
                    key = f["minio_prefix"] + filename
                    body = (f"demo {i}/{count} for {proj['code']}/{f['name']}\n").encode()
                    s3.put_object(Bucket="ms-dev", Key=key, Body=body,
                                  ContentType="text/plain")
                    aid = _asset_uuid(f["id"], filename)
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
                            parent_type="sensitive_folder" if f["is_sensitive"] else "folder",
                            parent_id=str(f["id"]),
                        )
                    except Exception:
                        pass
                    total_assets += 1
        await session.commit()
    log.info("assets:%d 上传 + 索引", total_assets)

    await permissions.close()
    log.info("DONE — %d projects · %d folders · %d assets",
             len(DEMO_PROJECTS), total_folders, total_assets)


if __name__ == "__main__":
    asyncio.run(main())
