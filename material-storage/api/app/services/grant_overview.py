"""项目级授权总览 — admin 运维入口 (#138)。

聚合一个 project 下所有"通过授权/邀请获得"的 grant(不含 members section 已展示的项目
直接角色成员),供 admin 看"谁有临时/永久授权、到期时间、哪条 grant"并撤回。

覆盖三种 OpenFGA object type 的 grant relation:
  - project           : explicit_downloader            (approval 批准的项目级临时下载)
  - folder            : explicit_viewer/downloader/uploader (folder 直接 grant 或 approval)
  - sensitive_folder  : invited_* (永久邀请) / explicit_invited_* (临时邀请)

asset 级 explicit_downloader 不在此总览(asset 数量级不适合逐个 read 聚合,维度也不属
项目/folder 视图)。

到期来源:OpenFGA tuple 的 condition.context(grant_time + grant_duration)。
临时 vs 永久:无 condition 或 grant_duration == _PERMANENT_GRANT_SECONDS(100yr)→ 永久。
read 返回原始 tuple(含已过期僵尸 tuple,OpenFGA 不自动删),聚合时按 expires_at < now 过滤。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.tables import Folder, User
from app.services.permissions import PermissionsService

# 各 object type 的 grant relation 白名单 → (level, 是否 relation 本身就代表永久)
# relation 本身代表永久的(sensitive 的 invited_*)无 condition;其余靠 condition 判定。
_PROJECT_RELATIONS: dict[str, tuple[str, bool]] = {
    "explicit_downloader": ("download", False),
}
_FOLDER_RELATIONS: dict[str, tuple[str, bool]] = {
    "explicit_viewer":     ("view", False),
    "explicit_downloader": ("download", False),
    "explicit_uploader":   ("upload", False),
}
_SENSITIVE_RELATIONS: dict[str, tuple[str, bool]] = {
    "invited_viewer":              ("view", True),
    "invited_downloader":          ("download", True),
    "explicit_invited_viewer":     ("view", False),
    "explicit_invited_downloader": ("download", False),
}

_PERMANENT = PermissionsService._PERMANENT_GRANT_SECONDS


def _parse_expiry(condition: Any, relation_permanent: bool) -> tuple[bool, datetime | None]:
    """从 tuple condition 判定 (是否永久, 到期时间)。

    - relation 本身永久(sensitive invited_*) → (True, None)
    - 无 condition → (True, None)  视为永久
    - condition.grant_duration == 100yr → (True, None)
    - 否则 → (False, grant_time + grant_duration)
    """
    if relation_permanent:
        return (True, None)
    if condition is None:
        return (True, None)
    ctx = getattr(condition, "context", None) or {}
    gt = ctx.get("grant_time")
    dur = ctx.get("grant_duration", "0s")
    try:
        seconds = int(str(dur).rstrip("s"))
    except (ValueError, AttributeError):
        return (True, None)
    if seconds >= _PERMANENT:
        return (True, None)
    # condition 存在但 grant_time 缺失/格式坏 → 无法判定到期,当永久处理
    # (避免前端拿到 "临时但无 expires_at" 去画 countdown 炸掉)
    if not gt:
        return (True, None)
    try:
        expires = (
            datetime.fromisoformat(str(gt).replace("Z", "+00:00"))
            + timedelta(seconds=seconds)
        )
    except (ValueError, AttributeError):
        return (True, None)
    return (False, expires)


async def _read_object_grants(
    permissions: PermissionsService,
    *,
    object_type: str,
    object_id: str,
    object_name: str | None,
    relations: dict[str, tuple[str, bool]],
    now: datetime,
) -> list[dict]:
    """read 单 object 的 tuple,白名单过滤 + 解析,返回未过期的 grant 记录。"""
    from openfga_sdk.models import ReadRequestTupleKey

    resp = await permissions._client.read(  # type: ignore[attr-defined]
        ReadRequestTupleKey(object=f"{object_type}:{object_id}")
    )
    out: list[dict] = []
    for t in resp.tuples:
        rel = t.key.relation
        if rel not in relations:
            continue
        level, relation_permanent = relations[rel]
        subject = t.key.user                       # "user:ou_xxx" / "group:gid#member"
        kind, rest = subject.split(":", 1)
        sid = rest.rsplit("#", 1)[0]               # 去 #member 后缀

        is_permanent, expires_at = _parse_expiry(
            getattr(t.key, "condition", None), relation_permanent
        )
        # 过滤已过期的僵尸 tuple(临时且到期 < now)
        if not is_permanent and expires_at is not None and expires_at < now:
            continue

        out.append({
            "subject": subject,
            "kind": kind,                          # user / group / department
            "subject_id": sid,
            "name": None,                          # user 类型后面批量查 db
            "object_type": object_type,
            "object_id": object_id,
            "object_name": object_name,
            "relation": rel,
            "level": level,                        # view / download / upload
            "permanent": is_permanent,
            "expires_at": expires_at.isoformat() if expires_at else None,
        })
    return out


async def list_project_grants(
    db: AsyncSession,
    permissions: PermissionsService,
    project_id: uuid.UUID,
) -> list[dict]:
    """聚合 project + 项目下所有 folder / sensitive_folder 的授权 grant。"""
    now = datetime.now(timezone.utc)

    # 项目下所有 folder(区分 sensitive)
    res = await db.execute(
        select(Folder.id, Folder.name, Folder.is_sensitive).where(
            Folder.project_id == project_id
        )
    )
    folders = res.all()

    records: list[dict] = []
    # project 级
    records.extend(await _read_object_grants(
        permissions, object_type="project", object_id=str(project_id),
        object_name=None, relations=_PROJECT_RELATIONS, now=now,
    ))
    # folder / sensitive_folder 级
    for fid, fname, is_sensitive in folders:
        otype = "sensitive_folder" if is_sensitive else "folder"
        rels = _SENSITIVE_RELATIONS if is_sensitive else _FOLDER_RELATIONS
        records.extend(await _read_object_grants(
            permissions, object_type=otype, object_id=str(fid),
            object_name=fname, relations=rels, now=now,
        ))

    # 批量查 user name(group/department 显 id 占位,与 folders.list_members 一致)
    user_sids = [r["subject_id"] for r in records if r["kind"] == "user"]
    if user_sids:
        ures = await db.execute(
            select(User.feishu_open_id, User.name).where(
                User.feishu_open_id.in_(user_sids)
            )
        )
        name_by_oid = {oid: name for oid, name in ures.all()}
        for r in records:
            if r["kind"] == "user":
                r["name"] = name_by_oid.get(r["subject_id"], r["subject_id"][:12] + "…")
    for r in records:
        if r["kind"] != "user" and r["name"] is None:
            label = "用户组" if r["kind"] == "group" else "部门"
            r["name"] = f"{label} {r['subject_id'][:12]}…"

    # 排序:临时在前(admin 更关心)、到期近的在前、user 优先
    def _rank(r: dict) -> tuple:
        return (
            0 if not r["permanent"] else 1,
            r["expires_at"] or "9999",
            0 if r["kind"] == "user" else 1,
            r["name"] or "",
        )
    records.sort(key=_rank)
    return records
