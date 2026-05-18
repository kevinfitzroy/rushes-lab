# material-storage 运维手册

> 适用范围:PoC server2 部署(8.156.34.238)+ 反代 server1。
> 适用对象:系统管理员 / 维护工程师。
> 最后更新:2026-05-17

---

## 0. 快速入口

```bash
# SSH 进 PoC server
ssh root@8.156.34.238

# 工作目录(docker compose 项目根)
cd /root/material-storage-api

# 容器一览
docker ps --format "table {{.Names}}\t{{.Status}}"
```

容器清单(全部 Up):

| 容器 | 作用 |
|---|---|
| `ms-api` | FastAPI 业务后端(127.0.0.1:8200) |
| `ms-worker` | arq 后台 worker(缩略图 + 定时任务) |
| `ms-db` | PostgreSQL 16 |
| `ms-redis` | Redis 7(arq queue + cache) |
| `poc-pigsty-minio` | MinIO 对象存储 |
| `poc-openfga` + `poc-openfga-db` | OpenFGA 权限引擎 + Postgres |
| `poc-nginx` | 反代 → 80 端口对外(ms-api + MinIO 静态) |
| `seafile` / `seafile-mysql` / `seafile-minio` | 遗留 PoC,与本应用无关 |

---

## 1. 系统 admin 管理(重点)

系统 admin = `organization#admin` OpenFGA tuple。**只有系统 admin 可创建项目**;UI 不提供 promote/demote(防误操作),只能后台命令。

**关键事实**:
- 系统 admin **数量无硬上限**(可加多个;典型用法见下面"典型场景")
- 系统 admin 在 **所有 project / folder / asset** 上拥有完整权限(view / download / upload / admin / share / delete),无需另外 grant(PR #77 起 backend 全覆盖直通)
- 系统 admin 仍然走 audit(下载 / 删除 / access_denied 等照记)

```bash
# 列当前所有系统 admin(包括所有 ou_*)
docker exec ms-api python -m scripts.grant_org_admin --list

# 添加一个系统 admin(用飞书 open_id;再跑一次 = 加第二个,不冲突)
docker exec ms-api python -m scripts.grant_org_admin ou_xxxxxxxxxxxx

# 撤销
docker exec ms-api python -m scripts.grant_org_admin --revoke ou_xxxxxxxxxxxx
```

### 如何拿到某个 user 的 open_id

让用户先去 web 用飞书 OIDC 登录一次(确保 db 有 user 行),然后:

```bash
docker exec ms-db psql -U msuser -d material_storage \
  -c "SELECT feishu_open_id, name, email FROM users WHERE name LIKE '%张三%';"
```

或者用 admin 自己登录后的 `/api/v1/auth/me` 接口看自己的 open_id。

### 典型场景

| 场景 | 命令 |
|---|---|
| 现任系统 admin 离职,要换人 | `--revoke <旧>` + 不带 flag `<新>` |
| 一个权限太集中,临时多加一个 | 不带 flag `<新>`(共存) |
| 紧急锁定:除当前所有人外 | `--list` 看清单 → 逐个 `--revoke` 保留要保的 |

### 边界规则

- 系统 admin **数量无硬上限**(模型支持多);产品上"默认 1 个"是惯例,不是 enforce
- 撤销自己:命令不阻止 — 撤销后立即无法再调 grant 命令(其他 admin 可救);**谨慎**
- 撤销项目 admin(`project#admin`):走 web ProjectMembersDrawer,不要在这里操作

---

## 2. 部署

### 2.0 推荐:一键 deploy 脚本(2026-05-18 起)

```bash
cd material-storage/api && bash scripts/deploy_server2.sh

# 推荐:带上本次解决的 issue 编号,前端会弹 modal 告诉 tester
cd material-storage/api && MAINTENANCE_ISSUES="101 104" bash scripts/deploy_server2.sh

# 或者 JSON 形式自定义 summary
cd material-storage/api && MAINTENANCE_ISSUES='[{"number":101,"summary":"自定义说明"}]' bash scripts/deploy_server2.sh
```

含:**maintenance banner 开启 (step 0.5, PR #108)** + rsync + docker compose up -d --build(含 ms-worker PR #103)+ alembic migrate + dev_bootstrap(⚠ #69 stale 已知 fail-soft)+ **demo-onboarding seed (step 6.5, PR #97)** + e2e + large file + **forensic log 备份 (step 3.5, PR #95)** + **banner 撤销 (step 9.5, PR #108)**。

**Maintenance banner**(PR #108):deploy 开始前 0.5 步会 SETEX redis `maintenance:banner` 一个 JSON,前端 ≤8s 内弹"系统升级中" modal(不可关 + 倒计时 + issue list);step 9.5 DEL 后前端转 6s "升级完成"自动关。900s TTL 兜底脚本崩了 banner 自然消失。MAINTENANCE_ISSUES 是 bare 数字时脚本会 `gh issue view` 自动拉 title。**注意:只保护已加载的 tab** — 新打开 tab 在 ms-api 重启那 30-60s 拿不到 SPA bundle,看不到 modal,这是 acceptable 取舍。

step 6/7/8 现在用 set -o pipefail + warn 替代假 ok(PR #95)— 看到 ⚠ 不阻塞 deploy,看到红色 ✗ 才需 follow up。

下面 §2.1-2.3 是手动分步,需要 surgical 操作时用。

### 2.1 后端代码更新(改 .py)

```bash
# 本地 rsync(开发机)
rsync -avz material-storage/api/app/ root@8.156.34.238:/root/material-storage-api/app/

# server 内重载
ssh root@8.156.34.238 'docker restart ms-api ms-worker'
```

`docker restart` 即可(不用 `--force-recreate`),因为 `.py` 通过 bind mount 实时生效。
**ms-worker 跟 ms-api 都要 restart**;一键脚本 step 4 已自动包含。

### 2.2 .env 改动

```bash
# 修 .env 后必须 force-recreate(docker restart 不重读 env_file)
ssh root@8.156.34.238 'cd /root/material-storage-api && docker compose up -d --force-recreate ms-api ms-worker'
```

### 2.3 前端代码更新

```bash
# 本地 build → dist 自动输出到 api/app/static/web/
cd material-storage/web && pnpm build

# 同步到 server2(bind mount 立即生效,无需重启)
rsync -avz --delete material-storage/api/app/static/web/ \
  root@8.156.34.238:/root/material-storage-api/app/static/web/
```

### 2.4 force-recreate 副作用

`docker compose up -d --force-recreate ms-api`:
- 容器 IP 漂移 → `poc-nginx` 缓存的 upstream DNS 失效 → **502**
- 容器内 `pip install` 的临时依赖丢失(测试用 pytest 等)

修法见 §6。

---

## 3. 飞书通讯录同步

### 3.1 冷启动全量同步

新装环境 / OpenFGA store 重建后跑一次:

```bash
docker exec ms-api python -m scripts.sync_feishu_contacts
```

行为:
- 通过 `/open-apis/contact/v3/scopes` 拿 app 可见顶级部门
- BFS 递归拉子部门 + 每部门下 user → DB upsert + OpenFGA org/dept tuples
- 拉用户组成员 → OpenFGA group tuples(若 `contact:group:readonly` 权限未开,优雅 skip)

### 3.2 增量同步(自动,不用手动操作)

飞书后台事件订阅 `https://rusheslab.taoxiplan.com/api/v1/webhooks/feishu`,events:
- `contact.user.created_v3` → DB upsert + dept tuple
- `contact.user.updated_v3` → diff dept_ids → 增/删 tuple
- `contact.user.deleted_v3` → **离职闭环**:revoke 所有 OpenFGA tuple + DB `is_active=false`
- `contact.department.updated_v3` → 重写部门 nesting

如果 webhook 没收到事件,检查:
1. 飞书后台 → 事件订阅 → URL 配的对
2. `docker exec ms-api curl -s http://127.0.0.1:8000/healthz` 通
3. `poc-nginx` 转发 OK(`docker logs poc-nginx --tail=20`)

### 3.3 飞书后台所需权限(检查清单)

| 权限 scope | 用途 | 必需? |
|---|---|---|
| `contact:contact.base:readonly` | 拉 user/dept | ✅ |
| `contact:user.base:readonly` | user 详情 | ✅ |
| `contact:department.base:readonly` | dept 详情 | ✅ |
| `contact:group:readonly` | 用户组同步 | 可选(没开会 skip) |
| `im:message:send_as_bot` | 发 IM 卡片 | ✅(权限/分享/邀请卡片) |
| 应用机器人能力启用 | 同上 | ✅ |
| 消息卡片请求网址 | 卡片回调按钮 | ✅(同 webhook URL) |
| 通讯录授权范围 | 决定 app 可见哪些部门 | 全公司 / 指定部门 |

---

## 4. 缩略图 worker

### 4.1 新上传自动生成

`POST /assets/uploads/{id}/complete` 完成后按 content_type 分流 enqueue arq job:

| content_type | worker function | 库 |
|---|---|---|
| `image/*` | `generate_thumbnail`(PR #57) | Pillow 1024px → JPEG q=80 |
| `video/*` | `generate_video_thumbnail`(PR #102 / issue #101) | ffmpeg `-ss 1` 抽帧 → 1024px JPEG q=3 |

两者都存 `thumbnails/{aid}.jpg` + 写 `asset.tags.thumbnail_key`,前端 AssetThumbnail 零差异显示。

**视频缩略图 50MB cap pilot**:size > 50MB → `status=skip_too_large` 不进 ffmpeg(ROADMAP §63 风险段)。fail-soft:ffmpeg 超时 30s / 抽帧失败 → `asset.tags.thumbnail_failed='...'`,asset 仍可用。

### 4.2 backfill 老 image asset

```bash
docker exec ms-api python -m scripts.backfill_thumbnails
```

行为:扫所有 `content_type=image/*` 且 `tags` 无 `thumbnail_key` 的 asset → enqueue。

> 视频 backfill 脚本 `scripts/backfill_video_thumbnails.py` 仍 pending(issue #101 checklist 剩条);需要时按图片版本 clone。

### 4.3 worker 日志

```bash
docker compose -f /root/material-storage-api/docker-compose.yml logs --tail=50 ms-worker
```

启动日志期望:`Starting worker for 4 functions: generate_thumbnail, generate_video_thumbnail, mark_expired_approvals, cron:mark_expired_approvals`(PR #102 起;若看到 `transcode_proxy` 说明跑的是旧 process,需 `docker compose restart ms-worker`)
成功:`0.21s ← <jobid>:generate_thumbnail ● {'status': 'ok', ...}`
失败:`failed asset=<id> err=...`(具体 traceback 在更早行)

### 4.4 cron 定时任务

每 5 分钟自动跑一次 `mark_expired_approvals`(把过期的 approved 申请 status → expired)。

---

## 5. 审计后台

### 5.1 UI 查

打开 https://rusheslab.taoxiplan.com/ms-static/web/admin/audit

权限:**任意 admin**(系统 admin 或任意 project admin)。

### 5.2 CSV 导出

UI 上"导出 CSV"按钮,或直接 curl:

```bash
curl 'https://rusheslab.taoxiplan.com/api/v1/admin/audit/export.csv?from=2026-05-01T00:00:00Z&to=2026-06-01T00:00:00Z' \
  -b 'ms_session=<your-jwt>' \
  -o audit-may.csv
```

最多 50000 行,UTF-8 BOM(Excel 直接打开)。

### 5.3 直接 SQL 查

```bash
docker exec ms-db psql -U msuser -d material_storage -c "
  SELECT event_time, event_type, actor_name_snapshot AS actor, details
  FROM audit_events
  WHERE event_type = 'access_denied' AND event_time > now() - interval '7 days'
  ORDER BY event_time DESC LIMIT 50;
"
```

---

## 6. 排查 cheat sheet

### 6.1 业务挂了 → 外网 502/403

最常见:容器 `force-recreate` 后 IP 漂移,`poc-nginx` upstream DNS 缓存 stale。

```bash
# 一键修
ssh root@8.156.34.238 'docker restart poc-nginx'

# 验证
curl -s -o /dev/null -w "%{http_code}\n" https://rusheslab.taoxiplan.com/healthz
# 应返 200
```

### 6.1.5 forensic — 拿 ms-api 上一轮日志(PR #95 起)

`docker compose up -d --build` recreate ms-api 会丢旧 logs(`docker logs ms-api` 只剩本次启动后的几行)。deploy 脚本 step 3.5 自动备份到 server2 `/tmp/ms-api-{ts}.log`:

```bash
ssh root@8.156.34.238 'ls -lt /tmp/ms-api-*.log | head -5'
# 选要看的 timestamp
ssh root@8.156.34.238 'tail -200 /tmp/ms-api-20260518-160000.log | grep -i error'
```

`/tmp` 重启会丢,但 deploy 间隔够短,排查 bug 时基本能拿到上一轮窗口。

### 6.2 ms-api 启动失败 ImportError

可能 rsync 路径错把 `models/__init__.py` 覆盖到 `app/__init__.py`(都叫 `__init__.py`)。
确保 rsync 时**带完整路径**:

```bash
# ❌ 错(会把多个 __init__.py 平铺到 app/)
rsync -avz app/models/__init__.py app/main.py root@...:/root/material-storage-api/app/

# ✅ 对(分批)
rsync -avz app/main.py root@...:/root/material-storage-api/app/
rsync -avz app/models/__init__.py root@...:/root/material-storage-api/app/models/

# 或用 staging
rsync -avz app/main.py app/models/__init__.py root@...:/tmp/_b/
ssh root@... 'cp /tmp/_b/main.py /root/material-storage-api/app/ && cp /tmp/_b/__init__.py /root/material-storage-api/app/models/'
```

修复:从本地 rsync 正确的 `app/__init__.py` 回去(只有 `__version__`),再 `docker restart ms-api`。

### 6.3 飞书 IM 卡片不发(代码层 best-effort,不阻塞业务)

```bash
# 验 token + 注册的 handler
curl -s 'https://rusheslab.taoxiplan.com/api/v1/admin/feishu/health' \
  -b 'ms_session=<jwt>' | python3 -m json.tool

# 推一张测试卡到自己
curl -X POST 'https://rusheslab.taoxiplan.com/api/v1/admin/feishu/test-card' \
  -H 'Content-Type: application/json' \
  -b 'ms_session=<jwt>' \
  -d '{"template":"approval"}'
```

常见错误:
- `230006 Bot ability is not activated` → 飞书后台启用机器人能力
- `99991672 Access denied … im:message:send_as_bot` → 飞书后台申请权限
- `99992351 invalid open_id` → 用户没在飞书企业内 / open_id 错

### 6.4 OpenFGA tuple 重复 / 不存在错误

`grant_explicit_download` 已自动 delete-then-write 处理重复。其他 grant 如遇 `tuple already existed`:

```bash
# 手动清某 user 全部 tuple(慎用 — 等同离职闭环)
docker exec ms-api python -c "
import asyncio
from app.services.permissions import create_permissions_service
from app.settings import get_settings
async def main():
    p = await create_permissions_service(get_settings())
    n = await p.revoke_user_completely('ou_xxxxxxxxxxxx')
    print('revoked', n)
asyncio.run(main())
"
```

### 6.5 pytest 跑不动 / 数 重复

```bash
# 清干净 + 重 cp
ssh root@8.156.34.238 'docker exec ms-api rm -rf /app/tests && docker cp /root/material-storage-api/tests ms-api:/app/tests && docker cp /root/material-storage-api/pyproject.toml ms-api:/app/pyproject.toml && docker exec ms-api pip install -q pytest pytest-asyncio && docker exec ms-api python -m pytest tests/ -q'
```

`force-recreate` 后 dev 依赖(pytest)需重装。

---

## 7. 数据库 / OpenFGA 重置(灾后或开发期清理)

### 7.1 重置 OpenFGA store(常用 — 模型升级时)

```bash
# 删旧 store
ssh root@8.156.34.238 'echo y | docker run --rm -i --network poc-pigsty-minio_poc-net \
  openfga/cli:latest store delete --api-url http://poc-openfga:8080 --store-id <STORE_ID>'

# 推 model-only yaml(本地准备 store-model-only.fga.yaml)
scp store-model-only.fga.yaml root@8.156.34.238:/tmp/
ssh root@8.156.34.238 'docker run --rm --network poc-pigsty-minio_poc-net -v /tmp:/data \
  openfga/cli:latest store import --api-url http://poc-openfga:8080 --file /data/store-model-only.fga.yaml'
# 返回 {"store":{"id":"<NEW>"}, "model":{"authorization_model_id":"<MODEL>"}}

# 更 .env
ssh root@8.156.34.238 "sed -i 's/^OPENFGA_STORE_ID=.*/OPENFGA_STORE_ID=<NEW>/' /root/material-storage-api/.env"

# force-recreate ms-api
ssh root@8.156.34.238 'cd /root/material-storage-api && docker compose up -d --force-recreate ms-api'

# 重跑 seed(项目/folder/asset/tuples)+ 通讯录同步
docker exec ms-api python -m scripts.seed_demo_data
docker exec ms-api python -m scripts.sync_feishu_contacts
docker exec ms-api python -m scripts.grant_org_admin ou_<你的 open_id>   # 重设系统 admin
```

### 7.2 重置 PostgreSQL 表(更激进)

```bash
docker exec ms-db psql -U msuser -d material_storage -c "
  TRUNCATE TABLE assets, folders, projects, approvals CASCADE;
  TRUNCATE TABLE audit_events;
"
# users / organizations 保留;再跑 seed
```

### 7.3 重置 MinIO bucket(更激进 — 删全部文件)

```bash
docker exec poc-pigsty-minio mc rm --recursive --force --dangerous local/ms-dev
docker exec poc-pigsty-minio mc mb local/ms-dev
```

---

## 8. 关键配置 / 服务器清单

### 8.1 域名 / 反代

- **域名**:`rusheslab.taoxiplan.com`
- **server1**(47.109.30.236):Caddy + 域名 → 反代 server2:80
- **server2**(8.156.34.238):
  - `poc-nginx`(80 端口)→ 反代:
    - `/api/v1/*` → `ms-api:8000`
    - `/ms-static/web/*` → `ms-api:8000/static/web/`
    - `/ms-dev/*` → `poc-pigsty-minio:9000/ms-dev/`(MinIO 文件直传/直下)

### 8.2 飞书 app

- `cli_aa8dbee01fb99bb3`
- redirect_uri:`https://rusheslab.taoxiplan.com/api/v1/auth/callback`
- 事件 webhook:`https://rusheslab.taoxiplan.com/api/v1/webhooks/feishu`
- 卡片回调:同上
- web H5 入口:`https://rusheslab.taoxiplan.com/ms-static/web/`

### 8.3 default organization

- DB id:`00000000-0000-0000-0000-0000000000a1`
- 飞书 tenant_key:`dev_tenant_001`(冷启动 seed 用,生产替为真 tenant_key)
- `.env`: `DEFAULT_ORGANIZATION_ID=00000000-0000-0000-0000-0000000000a1`

### 8.4 OpenFGA

- store_id:见 `/root/material-storage-api/.env` `OPENFGA_STORE_ID`
- 当前 model v4(`material-storage/poc/openfga/store.fga.yaml`)
- Playground UI(本地 SSH tunnel):`ssh -L 3001:127.0.0.1:3001 root@8.156.34.238` → http://localhost:3001/playground

### 8.5 MinIO

- bucket:`ms-dev`(PoC 全部 project 共用,通过 key prefix 区分)
- 缩略图:`thumbnails/{asset_id}.jpg`
- 凭证:`MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` in `.env`
- 控制台:`https://rusheslab.taoxiplan.com:9001`(或 host:9001 内网)

### 8.6 .env 关键字段

```
DB_URL=postgresql+asyncpg://msuser:mspass@ms-db:5432/material_storage
REDIS_URL=redis://ms-redis:6379/0
MINIO_ENDPOINT_INTERNAL=http://poc-pigsty-minio:9000
MINIO_ENDPOINT_PUBLIC=https://rusheslab.taoxiplan.com
OPENFGA_API_URL=http://poc-openfga:8080
OPENFGA_STORE_ID=01KRRR86H5HDM0KP0ZKBZC19TN
FEISHU_APP_ID=cli_aa8dbee01fb99bb3
FEISHU_APP_SECRET=<secret>
FEISHU_VERIFICATION_TOKEN=<token>
FEISHU_IM_ENABLED=true
WEB_APP_BASE_URL=https://rusheslab.taoxiplan.com/ms-static/web/
DEFAULT_ORGANIZATION_ID=00000000-0000-0000-0000-0000000000a1
```

---

## 9. 紧急联系流程

1. **业务挂了**(外网 502 / 500)
   - 第一步:`ssh root@8.156.34.238 'docker restart poc-nginx'`(80% 概率好)
   - 第二步:看 `docker compose logs --tail=30 ms-api`,粘报错给开发
2. **某 user 抱怨"看不到 project"**
   - 确认登录的飞书账号(让发 open_id)
   - SQL 查 `users.is_active`;若 false → 检查最近离职事件(audit `users.deleted_v3`)
   - OpenFGA check:`docker exec ms-api python -c "...permissions.check(...)"`(或 Playground)
3. **某 user 抱怨"应该是 admin 但操作 403"**
   - 检查是不是要求**系统** admin(只 1 人):`grant_org_admin --list`
   - 检查项目级 admin:打开 web ProjectMembersDrawer 看是否在列
4. **删错 user / 误撤销**
   - 飞书 user 撤销 tuple 是可逆的 — 重新建项目/邀请即恢复
   - DB `users.is_active=false` 是逻辑删,飞书重新发事件(任意操作)会重 upsert
