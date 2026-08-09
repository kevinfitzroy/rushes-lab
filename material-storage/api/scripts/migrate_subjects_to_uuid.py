"""存量 OpenFGA subject 迁移 — open_id / 飞书 gid → 本地 UUID(issue #148 / ADR-0007)。

执行(ms-api 容器内):
  docker exec ms-api python -m scripts.migrate_subjects_to_uuid            # dry-run(默认,只打印计划 + 写报告)
  docker exec ms-api python -m scripts.migrate_subjects_to_uuid --apply    # 真重写

⚠️ 部门轴先行(ADR-0007 已砍 department 轴;cutover 前必须处理,判断存量
   一律查 OpenFGA store,dry-run 输出的 department_skipped 就是全量清单):
   1. 先列出全部 department tuple(dry-run 报告 department_tuples 字段)
   2. 把需要保留的部门授权**物化成本地组或用户直授**(admin 后台建组/加人/授原权限)
   3. 确认处理完再 --apply;存在存量 department tuple 时 --apply 会被拒绝,
      必须加 --skip-department-gate 才放行(不推荐)

行为(idempotent,重跑无副作用):
  1. db 读全量 users → {feishu_open_id: str(users.id)} 映射
  2. 快照(before):每个 user 用旧 subject user:<open_id> 跑 list_objects
     (project/folder/sensitive_folder/asset x can_view/can_download/can_upload/can_admin;
     无飞书身份的本地账号本就是新格式,直接用 user:<users.id> 快照,不拼 user:None)
  3. OpenFGA read 分页拉全量 tuple,逐条制定重写计划:
     - user:<open_id>         → user:<users.id UUID>(映射不到 → 记 unknown_open_id,跳过不删)
     - user:<UUID 且在 users> → 已是新格式,跳过
     - group:<飞书 gid>[#member] → group:<本地 groups.id UUID>[#member]
       (本地组 id:同名组已存在 → 用同名组 id;否则 uuid5(NAMESPACE_DNS,
        "feishu:group:{gid}")确定性 id,与 _ensure_local_group 同一规则;
        --apply 时在 groups 表建行)
     - department:*(user 侧或 object 侧)→ 不迁,记 department_skipped,tuple 原样保留
       (见上方"部门轴先行":--apply 前必须已物化部门授权,否则拒绝执行)
     - object 侧 group:<飞书 gid> → 同步映射到本地组 uuid
  4. --apply:每个 batch(50)内**先写新 tuple 再删旧 tuple** —— 避免中间态丢权限;
     写遇到 'already existed' / 删遇到不存在都 tolerate(幂等)
  5. 同步重写 approvals.granted_tuple_ref JSONB 的 "user" 字段
  6. 快照(after):用新 subject 重算 list_objects,与 before per-user diff;
     报告写 ./subject_migration_report.json + 控制台摘要
     (验收:代表性用户迁移前后 list_objects 结果一致 → 看 consistency_ok / per_user_diff)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import uuid
from datetime import UTC, datetime
from typing import Any

from openfga_sdk.client.models import ClientTuple, ClientWriteRequest
from openfga_sdk.models import ReadRequestTupleKey
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.session import get_sessionmaker
from app.db.tables import ApprovalRequest, Group, User
from app.services.permissions import PermissionsService, create_permissions_service
from app.settings import get_settings

logging.basicConfig(level=logging.INFO, format="%(levelname)s — %(message)s")
log = logging.getLogger("migrate-subjects")

REPORT_PATH = "subject_migration_report.json"
BATCH = 50

_SNAPSHOT_TYPES = ("project", "folder", "sensitive_folder", "asset")
_SNAPSHOT_RELATIONS = ("can_view", "can_download", "can_upload", "can_admin")


def _local_group_uuid(feishu_gid: str) -> uuid.UUID:
    """飞书 gid → 本地 groups.id(deterministic,保证 idempotent)。"""
    return uuid.uuid5(uuid.NAMESPACE_DNS, f"feishu:group:{feishu_gid}")


def _is_uuid(s: str) -> bool:
    try:
        uuid.UUID(s)
    except ValueError:
        return False
    return True


async def _snapshot(
    permissions: PermissionsService, users: list[User], *, subject_fmt: str,
) -> dict[str, dict[str, list[str]]]:
    """每个 user 的可达对象集合。subject_fmt 用 '{id}' 占位('user:{open_id}' 或 'user:{uid}')。

    返 {str(user.id): {"<type>|<relation>": [object_id, ...](sorted)}}
    """
    out: dict[str, dict[str, list[str]]] = {}
    for u in users:
        if u.feishu_open_id:
            subject = subject_fmt.format(open_id=u.feishu_open_id, uid=str(u.id))
        else:
            # 本地账号无飞书身份:subject 本就是新格式 user:<users.id>,两种快照
            # 都用 uid —— 否则会拼出字面量 'user:None' 导致 before 恒空、验收恒红(F7-①)
            subject = f"user:{u.id}"
        per: dict[str, list[str]] = {}
        for obj_type in _SNAPSHOT_TYPES:
            for rel in _SNAPSHOT_RELATIONS:
                try:
                    ids = await permissions.list_objects(
                        user_subject=subject, relation=rel, object_type=obj_type,
                    )
                except Exception as e:
                    log.warning("snapshot list_objects fail user=%s %s/%s: %s",
                                subject, obj_type, rel, e)
                    ids = []
                per[f"{obj_type}|{rel}"] = sorted(ids)
        out[str(u.id)] = per
    return out


async def _read_all_tuples(permissions: PermissionsService) -> list[Any]:
    """分页读全量 tuple(ReadRequestTupleKey() 全空 = 不过滤)。"""
    tuples: list[Any] = []
    token: str | None = None
    while True:
        options: dict[str, Any] = {"page_size": 100}
        if token:
            options["continuation_token"] = token
        resp = await permissions._client.read(  # type: ignore[attr-defined]
            ReadRequestTupleKey(), options=options,
        )
        tuples.extend(resp.tuples or [])
        token = getattr(resp, "continuation_token", None) or None
        if not token:
            break
    return tuples


async def _ensure_local_group(db: Any, feishu_gid: str) -> uuid.UUID:
    """建(或复用)本地组行,返本地 group uuid。name = 旧飞书 gid。

    复用优先级:同 id(uuid5 确定性)→ 同名(手工已建)。
    """
    gid_uuid = _local_group_uuid(feishu_gid)
    existing = await db.get(Group, gid_uuid)
    if existing is not None:
        return existing.id
    res = await db.execute(select(Group).where(Group.name == feishu_gid))
    by_name = res.scalar_one_or_none()
    if by_name is not None:
        return by_name.id
    await db.execute(
        pg_insert(Group)
        .values(id=gid_uuid, name=feishu_gid,
                description=f"migrated from feishu group {feishu_gid}(#148)")
        .on_conflict_do_nothing(index_elements=["id"])
    )
    await db.commit()
    return gid_uuid


def _write_report(report: dict[str, Any]) -> None:
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="真重写(默认 dry-run 只打印计划 + 写报告)")
    parser.add_argument("--skip-department-gate", action="store_true",
                        help="跳过部门轴检查:存在存量 department tuple 时仍允许 --apply(不推荐)")
    args = parser.parse_args()

    settings = get_settings()
    sm = get_sessionmaker()
    permissions = await create_permissions_service(settings)

    # ─── 1) 映射 + 已知 UUID 集合 ─────────────────────────────────────────
    async with sm() as db:
        users = list((await db.execute(select(User))).scalars().all())
    open_id_to_uid = {u.feishu_open_id: str(u.id) for u in users if u.feishu_open_id}
    known_uids = {str(u.id) for u in users}
    log.info("users: %d(映射 %d 个 open_id)", len(users), len(open_id_to_uid))

    # ─── 2) before 快照(旧 subject)───────────────────────────────────────
    log.info("snapshot before(旧 subject user:<open_id>)…")
    before = await _snapshot(permissions, users, subject_fmt="user:{open_id}")

    # ─── 3) 全量 tuple → 重写计划 ─────────────────────────────────────────
    all_tuples = await _read_all_tuples(permissions)
    log.info("OpenFGA tuples total: %d", len(all_tuples))

    async with sm() as db:
        existing_groups = list((await db.execute(select(Group))).scalars().all())
    known_group_ids = {str(g.id) for g in existing_groups}
    name_to_gid = {g.name: g.id for g in existing_groups}

    def _resolve_group_id(feishu_gid: str) -> uuid.UUID:
        """计划期确定本地组 id,与 _ensure_local_group 同一规则(F7-③):

        同名组已存在 → 用同名组的 id;否则 uuid5 确定性 id。
        原来只按 uuid5 计划、_ensure_local_group 同名复用另一 id,导致写出的
        tuple 指向不存在的 group 行(权限悬空)。
        """
        return name_to_gid.get(feishu_gid, _local_group_uuid(feishu_gid))

    # (old_key, new_key) 对;key = (user, relation, object, condition)
    plan: list[tuple[Any, ClientTuple, ClientTuple]] = []
    unknown_open_ids: set[str] = set()
    department_skipped: list[dict[str, str]] = []
    already_new = 0
    group_id_map: dict[str, uuid.UUID] = {}   # 飞书 gid → 本地 uuid(计划期确定)

    for t in all_tuples:
        old_user, relation, obj = t.key.user, t.key.relation, t.key.object
        condition = getattr(t.key, "condition", None)

        # department 轴(user 侧或 object 侧)不迁,原样保留
        if old_user.startswith("department:") or obj.startswith("department:"):
            department_skipped.append(
                {"user": old_user, "relation": relation, "object": obj}
            )
            continue

        # user 侧重写
        new_user = old_user
        skip = False
        if old_user.startswith("user:"):
            sid = old_user.split(":", 1)[1]
            if sid in open_id_to_uid:
                new_user = f"user:{open_id_to_uid[sid]}"
            elif _is_uuid(sid) and sid in known_uids:
                already_new += 1  # 已是新格式
                skip = True
            else:
                unknown_open_ids.add(sid)  # 映射不到 → 跳过不删(防丢权限)
                skip = True
        elif old_user.startswith("group:"):
            gid, suffix = old_user.split(":", 1)[1], ""
            if "#" in gid:
                gid, suffix = gid.split("#", 1)[0], "#" + gid.split("#", 1)[1]
            if _is_uuid(gid) and gid in known_group_ids:
                already_new += 1
                skip = True
            else:
                local = group_id_map.setdefault(gid, _resolve_group_id(gid))
                new_user = f"group:{local}{suffix}"
        # 其他 user 侧(organization: / project: / folder: parent 等)不动

        # object 侧 group:<飞书 gid> 映射
        new_obj = obj
        if obj.startswith("group:"):
            gid = obj.split(":", 1)[1]
            if not (_is_uuid(gid) and gid in known_group_ids):
                local = group_id_map.setdefault(gid, _resolve_group_id(gid))
                new_obj = f"group:{local}"

        if skip or (new_user == old_user and new_obj == obj):
            if not skip:
                already_new += 1
            continue

        old_ct = ClientTuple(user=old_user, relation=relation, object=obj)
        new_ct = ClientTuple(
            user=new_user, relation=relation, object=new_obj, condition=condition,
        )
        plan.append((t, old_ct, new_ct))

    log.info("计划:重写 %d 条;已是新格式 %d;department 跳过 %d;未知 open_id 跳过 %d",
             len(plan), already_new, len(department_skipped), len(unknown_open_ids))

    # ─── 3.5) 部门轴闸门(F7-②):存量 department tuple 未物化前拒绝 --apply ──
    if args.apply and department_skipped and not args.skip_department_gate:
        print("\n=== 部门轴权限存在,拒绝执行 --apply ===")
        print("迁移只把 user 侧 subject 换成 UUID,department tuple 原样保留 →")
        print("迁移后旧 subject 的用户不再是部门 member,部门授权会**静默失效**。")
        print("cutover 前必须先把要保留的部门授权物化成本地组 / 用户直授")
        print("(判断存量一律查 OpenFGA store;下方列表即 dry-run 报告 department_tuples)。")
        print("确认全部处理完再重跑 --apply;确实确认无影响可加 --skip-department-gate 放行。")
        for d in department_skipped[:20]:
            print(f"  {d['user']} {d['relation']} {d['object']}")
        if len(department_skipped) > 20:
            print(f"  …共 {len(department_skipped)} 条,其余见报告 department_tuples")
        await permissions.close()
        return 3

    # ─── 4) approvals.granted_tuple_ref JSONB 重写计划 ─────────────────────
    async with sm() as db:
        approvals = list((await db.execute(select(ApprovalRequest))).scalars().all())
    approval_rewrites: list[tuple[ApprovalRequest, str]] = []  # (row, old_user)
    for ap in approvals:
        ref = dict(ap.granted_tuple_ref or {})
        u = ref.get("user")
        if not (isinstance(u, str) and u.startswith("user:")):
            continue
        sid = u.split(":", 1)[1]
        if sid in open_id_to_uid:
            approval_rewrites.append((ap, u))
        elif not (_is_uuid(sid) and sid in known_uids):
            unknown_open_ids.add(sid)

    # ─── 5) apply ──────────────────────────────────────────────────────────
    written = deleted = 0
    groups_created: list[str] = []
    if args.apply:
        # 本地组行(tuple 写之前建好)
        if group_id_map:
            async with sm() as db:
                for feishu_gid in sorted(group_id_map):
                    await _ensure_local_group(db, feishu_gid)
            groups_created = sorted(group_id_map)
            log.info("本地组行就绪:%d(%s)", len(groups_created), groups_created)

        # batch 内先写新后删旧:中间态只有"新旧并存",不会丢权限
        for i in range(0, len(plan), BATCH):
            batch = plan[i : i + BATCH]
            try:
                await permissions._client.write(  # type: ignore[attr-defined]
                    ClientWriteRequest(writes=[n for _, _, n in batch])
                )
                written += len(batch)
            except Exception as e:
                # 部分已存在(重跑)→ 退化逐条写,tolerate 'already existed'
                log.warning("batch write fail(%s),逐条重试", e)
                for _, _, n in batch:
                    try:
                        await permissions._client.write(  # type: ignore[attr-defined]
                            ClientWriteRequest(writes=[n])
                        )
                        written += 1
                    except Exception as e2:
                        if "already existed" in str(e2):
                            written += 1
                        else:
                            log.error("write fail %s: %s", n, e2)
            try:
                await permissions._client.write(  # type: ignore[attr-defined]
                    ClientWriteRequest(deletes=[o for _, o, _ in batch])
                )
                deleted += len(batch)
            except Exception as e:
                log.warning("batch delete fail(%s),逐条重试", e)
                for _, o, _ in batch:
                    try:
                        await permissions._client.write(  # type: ignore[attr-defined]
                            ClientWriteRequest(deletes=[o])
                        )
                        deleted += 1
                    except Exception as e2:
                        log.warning("delete fail(可能已不存在)%s: %s", o, e2)

        # approvals.granted_tuple_ref
        if approval_rewrites:
            async with sm() as db:
                for ap, _old_u in approval_rewrites:
                    row = await db.get(ApprovalRequest, ap.id)
                    if row is None:
                        continue
                    ref = dict(row.granted_tuple_ref or {})
                    sid = ref["user"].split(":", 1)[1]
                    ref["user"] = f"user:{open_id_to_uid[sid]}"
                    row.granted_tuple_ref = ref
                await db.commit()
            log.info("approvals.granted_tuple_ref 重写 %d 条", len(approval_rewrites))
    else:
        log.info("dry-run — 未写任何东西。加 --apply 执行重写")

    # ─── 6) after 快照 + diff + 报告 ───────────────────────────────────────
    per_user_diff: dict[str, Any] = {}
    consistency_ok: bool | None = None
    if args.apply:
        log.info("snapshot after(新 subject user:<users.id>)…")
        after = await _snapshot(permissions, users, subject_fmt="user:{uid}")
        consistency_ok = True
        for u in users:
            uid = str(u.id)
            b, a = before.get(uid, {}), after.get(uid, {})
            keys = set(b) | set(a)
            only_before = {k: b[k] for k in keys if b.get(k) and b.get(k) != a.get(k)}
            only_after = {k: a[k] for k in keys if a.get(k) and b.get(k) != a.get(k)}
            equal = not only_before and not only_after
            if not equal:
                consistency_ok = False
            per_user_diff[uid] = {
                "name": u.name,
                "open_id": u.feishu_open_id,
                "equal": equal,
                "only_before": only_before,
                "only_after": only_after,
            }

    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "applied": bool(args.apply),
        "counts": {
            "tuples_total": len(all_tuples),
            "tuples_rewritten": len(plan),
            "tuples_written": written,
            "tuples_deleted": deleted,
            "already_new": already_new,
            "department_skipped": len(department_skipped),
            "unknown_open_id_skipped": len(unknown_open_ids),
            "approvals_ref_rewritten": len(approval_rewrites) if args.apply else 0,
            "local_groups": sorted(str(v) for v in group_id_map.values()),
        },
        "unknown_open_ids": sorted(unknown_open_ids),
        "department_tuples": department_skipped,
        "group_id_map": {k: str(v) for k, v in sorted(group_id_map.items())},
        "consistency_ok": consistency_ok,
        "per_user_diff": per_user_diff,
    }
    await asyncio.to_thread(_write_report, report)

    print("\n=== subject migration summary ===")
    print(f"applied           : {args.apply}")
    print(f"tuples total      : {len(all_tuples)}")
    print(f"rewrite planned   : {len(plan)}")
    if args.apply:
        print(f"written / deleted : {written} / {deleted}")
        print(f"approvals ref     : {len(approval_rewrites)}")
    print(f"already new       : {already_new}")
    print(f"department skipped: {len(department_skipped)}(原样保留)")
    print(f"unknown open_ids  : {len(unknown_open_ids)} → {sorted(unknown_open_ids)}")
    if consistency_ok is not None:
        print(f"consistency_ok    : {consistency_ok}")
        bad = [uid for uid, d in per_user_diff.items() if not d["equal"]]
        if bad:
            print(f"不一致 user       : {bad}(详见报告 per_user_diff)")
    print(f"report            : {REPORT_PATH}")

    await permissions.close()
    return 0 if consistency_ok is not False else 4


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
