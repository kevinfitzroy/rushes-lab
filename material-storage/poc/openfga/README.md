# PoC — OpenFGA 权限引擎(Phase B 准备)

> 验证 OpenFGA 作 material-storage 业务权限引擎,解决 ADR-0005 §11.2 **Gap 1**(presigned URL 撤销)+ **Gap 5**(用户↔资源权限模型)。

## 结论(2026-05-16 实测)

**28/28 checks pass + 1/1 test pass** — OpenFGA 完美 fit material-storage 业务需求:
- ReBAC 模型表达 user × group × organization × project × folder × asset 自然继承
- **Conditional Tuples**(时间条件)优雅解 Gap 1:审批通过的临时 grant 自动过期,无需 cron 清理
- **敏感目录隔离**:`sensitive_folder` 独立 type,不从 project 自动继承 viewer,只 admin + explicit grant 可访问

## 部署(8.156.34.238 实测)

```yaml
# 已加入 ../minio/docker-compose.yml(同 docker network poc-net)
poc-openfga-db:    image: postgres:16-alpine
poc-openfga-migrate: image: openfga/openfga:latest  (init container)
poc-openfga:       image: openfga/openfga:latest  (port 127.0.0.1:8089→8080, 3001→3000)
```

部署一键:
```bash
cd /root/poc-pigsty-minio
docker compose up -d poc-openfga-db poc-openfga-migrate poc-openfga
```

## Model 设计要点

### 6 type + 1 condition

| Type | 关键 relations |
|---|---|
| `user` | (无 relations,作 actor)|
| `group` | `member: [user]` |
| `organization` | `admin / member: [user, group#member]` |
| `project` | `organization, admin, editor, viewer`(从 org admin 继承)|
| `folder` | `parent: [project, folder]`;**自动从 project 继承 viewer/editor/admin** |
| `sensitive_folder` | `parent: [project]`;**只 admin 自动 + `explicit_viewer: [user with non_expired_grant]`**(审批驱动) |
| `asset` | `parent: [project, folder, sensitive_folder]`;`can_view / can_download / can_edit / can_delete` |

### Condition

```fga
condition non_expired_grant(current_time: timestamp, grant_time: timestamp, grant_duration: duration) {
  current_time < grant_time + grant_duration
}
```

写 tuple 时:
```yaml
- user: user:bob
  relation: explicit_viewer
  object: sensitive_folder:client-private
  condition:
    name: non_expired_grant
    context:
      grant_time: "2026-05-16T10:00:00Z"
      grant_duration: 1h
```

Check 时业务后端传 `current_time`,OpenFGA 自动评估 grant 是否 expired。**不需要 cron 清理 expired grants**。

## 测试矩阵(28 个 check,全 pass)

| 场景 | 资源 | 操作 | 期望 |
|---|---|---|---|
| alice(org admin) | 任何 | 任何 | ✅ |
| bob(group → project editor) | normal asset | view/download/edit | ✅ |
| bob | normal asset | delete | ❌(非 admin)|
| bob | sensitive asset(grant 内 10:30) | view/download | ✅ |
| bob | sensitive asset(grant 边界 10:00)| view/download | ✅ |
| bob | sensitive asset(过期边界 11:00)| view/download | ❌ |
| bob | sensitive asset(完全过期 11:30)| view/download | ❌ |

跑测试:
```bash
docker run --rm -v /root/poc-pigsty-minio/openfga:/data \
  openfga/cli:latest model test --tests /data/store.fga.yaml
```

## 业务后端集成 sketch(Python material-storage backend)

```python
from openfga_sdk import OpenFgaClient, ClientConfiguration
from openfga_sdk.client.models import ClientCheckRequest

cfg = ClientConfiguration(
    api_url="http://poc-openfga:8080",
    store_id="01KRR4FJN1S3RS112BZPN3ZXRH",  # 实际从环境/启动时 list
    authorization_model_id="01KRR4FJN7QFZMAWFXQ2K9E7H1",
)
fga = OpenFgaClient(cfg)

# ─── 申请下载敏感文件流程 ───────────────────────
async def grant_sensitive_access(user_id: str, folder_id: str, duration_hours: int = 1):
    """飞书审批通过后调用,写一个 conditional tuple,自动过期。"""
    from datetime import datetime, timezone
    await fga.write(
        writes=[ClientTuple(
            user=f"user:{user_id}",
            relation="explicit_viewer",
            object=f"sensitive_folder:{folder_id}",
            condition=ClientCondition(
                name="non_expired_grant",
                context={
                    "grant_time": datetime.now(timezone.utc).isoformat(),
                    "grant_duration": f"{duration_hours}h",
                },
            ),
        )]
    )

# ─── 每次访问 check ─────────────────────────────
async def can_download(user_id: str, asset_id: str) -> bool:
    from datetime import datetime, timezone
    resp = await fga.check(ClientCheckRequest(
        user=f"user:{user_id}",
        relation="can_download",
        object=f"asset:{asset_id}",
        context={"current_time": datetime.now(timezone.utc).isoformat()},
    ))
    return resp.allowed

# ─── 离职闭环 ───────────────────────────────────
async def revoke_user_completely(user_id: str):
    """飞书 contact.user.deleted_v3 → 删 user 所有 tuple"""
    # OpenFGA 提供 list_users + read,业务封装 batch delete
    tuples = await fga.read(...)  # 找 user:bob 所有 relations
    await fga.write(deletes=tuples)
```

## 接 Gap 1(presigned URL 撤销)的优雅解

| 文件类型 | 路径 | 撤销机制 |
|---|---|---|
| 普通(folder)| 浏览器 → MinIO presigned URL 直传/直下 | 短 TTL(15min)+ 接受不可撤(15min 后过期)|
| **敏感**(sensitive_folder)| 浏览器 → **material-storage FastAPI 代理 stream** → MinIO | **每个 chunk** check OpenFGA;grant 过期立即拒;**不签 presigned URL**(避开 stateless 问题)|

ADR-0001 §4(b) "敏感目录代理路径" + OpenFGA conditional tuples = 完整 Gap 1 解。

## Playground UI(浏览器可视化操作)

OpenFGA 自带 Playground,可视化 model + tuples + run check:

```bash
# 本地起 SSH tunnel
ssh -L 3001:127.0.0.1:3001 -L 8089:127.0.0.1:8089 root@8.156.34.238

# 然后浏览器
http://localhost:3001/playground   # Playground UI
http://localhost:8089               # HTTP API(自检 / Postman 等)
```

⚠️ Playground 已被 OpenFGA 标记 deprecated(将来 release 移除),用作 PoC OK。生产用 `fga` CLI / SDK。

## 部署 footprint

| 容器 | 镜像 | 内存 | 用途 |
|---|---|---|---|
| poc-openfga | openfga/openfga:latest v1.15.1 | ~ 50 MB | API + Playground |
| poc-openfga-db | postgres:16-alpine | ~ 80 MB | 后端 |
| poc-openfga-migrate | openfga/openfga | (init,跑完退出)| schema migration |

总 ~ 130 MB 内存,轻量。

## 验证状态

| Phase | 状态 |
|---|---|
| OpenFGA + Postgres 部署可用 | ✅ |
| HTTP API healthz SERVING | ✅ |
| Authorization model upload + valid | ✅(via `store import`) |
| 28 checks(7 scenarios × ~ 4 actions)| ✅ 100% pass |
| 边界条件(grant 边界 10:00 / 过期边界 11:00) | ✅ 正确 |
| 业务后端 SDK 集成 | 🟡 Sketch 给出,Phase B 实际编码 |
| Playground UI 可访问(SSH tunnel) | ✅ |

## v2 — 简化模型(2026-05-16 next iter)

业务侧反馈:**不需要 sensitive/普通二分**;一切由角色驱动 + 申请补足。

Model v2 改:
- 删 `sensitive_folder` type → 统一 `folder` type
- 临时下载 grant `explicit_downloader` 移到 **project 级 + asset 级 双层**:
  - **project 级**:批量场景(实习生 30d、一次性批量审批整 project)
  - **asset 级**:单文件审批(每次申请一个 file,审批通过临时下载)
- material-storage backend 新增 `project.visibility` DB 字段(`public` / `private` / `stealth`)
  控制 metadata 列表可见性(不进 OpenFGA model)

**v2 PoC 通过:1/1 test + 29/29 check**,覆盖:
- alice (org admin) 全权
- bob (project editor) project 内全权
- charlie (file-level grant) grant 内/外 边界
- david (project-level grant 30d) member=false 但 can_download=true(`from parent or explicit_downloader`)

## 关联

- ADR-0005 §11.2 Gap 1(presigned URL 撤销)+ Gap 5(权限模型)
- ADR-0006 §1 + §10(权限引擎 + Gap update)
- OpenFGA: https://openfga.dev / Apache 2.0 / Auth0 + CNCF
- Pigsty MinIO PoC: `../minio/`
- material-storage api Phase B-2 配套:`../api/`
