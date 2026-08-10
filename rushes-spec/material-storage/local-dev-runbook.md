# 本地跑起来 runbook(无飞书 · 可测上传/下载/建号)

> 目标:在一台开发机上把完整 web 应用跑起来,能实测 **上传 / 下载 / 用户注册管理 / 登录改密 / 盲搜**。
> 前提:ADR-0007 之后已无飞书依赖 —— 登录走本地账号密码,不需要任何公网服务。
> 最后更新:2026-08-10。配套:[ops-manual](./ops-manual.md)(内网生产)、[ROADMAP](./ROADMAP.md)。

## 0. 先看这三条

1. **必须先有 [PR:0011 migration 修复]**。已 merge 的 `2026_08_09_0011` 直接对 `array_to_string(user_labels,' ')` 建 GIN 索引,而该函数在 PG 是 STABLE → `alembic upgrade head` **必然失败**,库建不起来。修复见 `research/review-2026-08-09-wave1-2.md` §R1。
2. **`.env.example` 现在可以直接 `cp` 就起**(补了 `WEB_APP_BASE_URL` / `DEFAULT_ORGANIZATION_ID` 两个必填项;之前照抄会直接 ValidationError)。
3. **macOS 上依赖要带 `sqlalchemy[asyncio]`**(greenlet 在 arm64 上不是自动依赖),否则任何异步 DB 调用直接 `ValueError: the greenlet library is required`。

## 1. 选哪条路

| | 方案 A:容器(推荐) | 方案 B:全原生 brew |
| --- | --- | --- |
| 需要装 | OrbStack(或 Docker Desktop / colima) | postgresql@16 · minio · openfga · fga CLI |
| 与生产一致 | ✅ 就是内网要用的那套 compose | ⚠️ 组件版本/拓扑自己维护 |
| 能跑仓库的 60 个集成测试 | ✅ `docker exec ms-api pytest tests/ -v` | ❌ 部分用例假设容器名 |
| 首次耗时 | ~20 min(拉镜像为主) | ~30 min(装 + 配 4 个服务) |
| 适合 | 想尽快看到真东西、之后还要上内网 | 坚决不装容器运行时 |

**推荐 A。** 这台机器实测:`redis` 已在跑、`postgresql@14` 装了但没起、有 `ffmpeg`/`nginx`/`node`/`pnpm`、**没有任何容器运行时**(docker/colima/podman/orb 都不在 PATH)。装 OrbStack 是一次性成本,换来的是和内网生产同一套 compose + 那 60 个集成测试能跑。

---

## 2. 方案 A:OrbStack + 仓库现成 compose

### A1. 装容器运行时

```bash
brew install orbstack        # 或 Docker Desktop;colima 也行(colima start --cpu 4 --memory 8)
```
装完确认 `docker ps` 能通。

### A2. 起依赖栈(MinIO + OpenFGA + nginx)

```bash
cd material-storage/poc/minio
docker compose up -d pigsty-minio poc-minio-thumbs poc-openfga-db poc-openfga-migrate poc-openfga poc-nginx
docker compose ps
```

- MinIO S3 API → `localhost:6100`,Console → `localhost:6101`(默认账号见 compose,本地不改也行)
- OpenFGA HTTP → `localhost:8089`,Playground → `localhost:3001`
- nginx → `localhost:80`(把 `/ms-static/*` 转 ms-api、`/ms-thumbs/*` 转缩略图 MinIO)
- `poc-console` / `poc-presigner` / `poc-webhook` / `seafile` 本地不需要,别起

### A3. 建 OpenFGA store + 推 model(**漏了这步所有权限判定恒 false**)

`scripts/openfga_write_model.sh` 是写死 server2 的(HOST + ssh),本地用下面这段:

```bash
cd material-storage/api
# 1) 建 store,拿 STORE_ID
STORE_ID=$(curl -s -X POST http://localhost:8089/stores \
  -H 'content-type: application/json' \
  -d '{"name":"material-storage-local"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')
echo "STORE_ID=$STORE_ID"

# 2) 从 store.fga.yaml 抽 model DSL
python3 -c "import yaml;print(yaml.safe_load(open('../poc/openfga/store.fga.yaml'))['model'])" > /tmp/model.fga

# 3) DSL → JSON 并写入 store(用官方 CLI 镜像,免装二进制)
MODEL_JSON=$(docker run --rm -i openfga/cli model transform --input-format fga < /tmp/model.fga)
curl -s -X POST "http://localhost:8089/stores/$STORE_ID/authorization-models" \
  -H 'content-type: application/json' -d "$MODEL_JSON" | head -c 200
```

> `.env` 不固定 `OPENFGA_MODEL_ID` 时 ms-api 自动取 store 的 latest model,所以只要写进去就行。

### A4. 写 `api/.env`

```bash
cd material-storage/api
cp .env.example .env
```
然后按 §4 的表改这几项(容器内互相用容器名):

```
MINIO_ENDPOINT_INTERNAL=http://poc-pigsty-minio:9000
MINIO_ENDPOINT_PUBLIC=http://localhost:6100      # ← 浏览器视角,必须可达
MINIO_DEFAULT_BUCKET=ms-dev
OPENFGA_API_URL=http://poc-openfga:8080
OPENFGA_STORE_ID=<A3 拿到的>
SESSION_COOKIE_SECURE=false                      # ← 本地 http,不改的话 cookie 永远存不下
SESSION_JWT_SECRET=<openssl rand -hex 32>
WEB_APP_BASE_URL=http://localhost:5173/ms-static/web/
```

### A5. 起 api 栈 + 建库 + 灌种子

```bash
cd material-storage/api
docker compose up -d --build          # ms-db / ms-redis / ms-api / ms-worker
docker compose exec ms-api alembic upgrade head
docker compose exec ms-api python -m scripts.dev_bootstrap
```

`dev_bootstrap` 输出里记下 `ADMIN_USER_ID`(固定 `00000000-0000-0000-0000-000000000001`,alice = org admin = 系统 admin)。

### A6. 前端

```bash
cd material-storage/web
pnpm install
pnpm dev        # http://localhost:5173/ms-static/web/,proxy /api → localhost:8200
```

浏览器开 **http://localhost:5173/ms-static/web/dev-login**。

---

## 3. 方案 B:全原生(不装容器)

### B1. 装 + 起服务

```bash
brew install postgresql@16 minio/stable/minio minio/stable/mc
brew services start postgresql@16
brew services start redis                      # 本机已在跑,跳过

# MinIO(单机单盘,够本地用)
mkdir -p ~/ms-local/minio
MINIO_ROOT_USER=msadmin MINIO_ROOT_PASSWORD=msadmin-local-2026 \
  minio server ~/ms-local/minio --address :9000 --console-address :9001 &
```

OpenFGA 没有稳定的 brew formula 保证,两条路二选一(**首次跑需自行确认命令名**):

```bash
# a) 官方 tap(若可用)
brew install openfga/tap/openfga openfga/tap/fga
# b) 直接下 release 二进制(github.com/openfga/openfga/releases 与 openfga/cli/releases)
```

OpenFGA 用本地 PG 做 datastore(重启不丢 store,省得每次改 .env):

```bash
createdb openfga
export OPENFGA_DATASTORE_URI="postgres://$(whoami)@localhost:5432/openfga?sslmode=disable"
openfga migrate --datastore-engine postgres --datastore-uri "$OPENFGA_DATASTORE_URI"
openfga run --datastore-engine postgres --datastore-uri "$OPENFGA_DATASTORE_URI" &   # :8080
```

### B2. 业务库

```bash
createuser -s msuser 2>/dev/null || true
psql -d postgres -c "ALTER USER msuser WITH PASSWORD 'mspass';"
createdb -O msuser material_storage
```

### B3. store + model

同 A3,把 `http://localhost:8089` 换成 `http://localhost:8080`;DSL→JSON 用本机 `fga` CLI:

```bash
fga model transform --input-format fga --file /tmp/model.fga > /tmp/model.json
curl -s -X POST "http://localhost:8080/stores/$STORE_ID/authorization-models" \
  -H 'content-type: application/json' -d @/tmp/model.json
```

### B4. `.env`(全 localhost)

```
DB_URL=postgresql+asyncpg://msuser:mspass@localhost:5432/material_storage
REDIS_URL=redis://localhost:6379/0
MINIO_ENDPOINT_INTERNAL=http://localhost:9000
MINIO_ENDPOINT_PUBLIC=http://localhost:9000
MINIO_ACCESS_KEY=msadmin
MINIO_SECRET_KEY=msadmin-local-2026
MINIO_DEFAULT_BUCKET=ms-dev
OPENFGA_API_URL=http://localhost:8080
OPENFGA_STORE_ID=<B3 拿到的>
SESSION_COOKIE_SECURE=false
WEB_APP_BASE_URL=http://localhost:5173/ms-static/web/
DEFAULT_ORGANIZATION_ID=00000000-0000-0000-0000-0000000000a1
ENV=dev
```

### B5. 起服务

```bash
cd material-storage/api
uv sync
uv run alembic upgrade head
uv run python -m scripts.dev_bootstrap
uv run uvicorn app.main:app --reload --port 8200     # ← 用 8200,对齐 vite proxy,省得改 vite.config
uv run arq app.workers.main.WorkerSettings &         # 缩略图 worker(本机已有 ffmpeg)

cd ../web && pnpm install && pnpm dev
```

浏览器开 **http://localhost:5173/ms-static/web/dev-login**。

> 方案 B 不需要 nginx:vite dev server 自己就挂在 `/ms-static/web/` 并把 `/api` 代理到 8200,和 `BrowserRouter basename` 天然对得上。想验证"构建产物由 ms-api 发布"的生产形态时才需要 nginx 做 `/ms-static/* → /static/*` 的 rewrite。

---

## 4. `.env` 关键项(两方案通用,踩过的坑都在这)

| key | 本地值 | 为什么会踩 |
| --- | --- | --- |
| `ENV` | `dev` | 不是 `dev` 时 `X-User-Id` 开发通道直接拒绝,首个管理员没法登录 |
| `SESSION_COOKIE_SECURE` | `false` | 默认 `true`;本地 http 下浏览器**静默丢弃** Set-Cookie,表现是"登录成功但立刻又跳登录页" |
| `MINIO_ENDPOINT_PUBLIC` | 浏览器真正能访问的 host:port | presigned URL 按这个 host 签名,写错 → 上传/下载 403 SignatureDoesNotMatch(P-10 老坑) |
| `MINIO_ENDPOINT_INTERNAL` | 容器名 or localhost | ms-api/worker 服务端调用用 |
| `OPENFGA_STORE_ID` | 每次新建 store 都变 | 忘了更新 → 所有 check 恒 false,页面全空还不报错 |
| `WEB_APP_BASE_URL` | `http://localhost:5173/ms-static/web/` | **Settings 必填**,缺了 ms-api 起不来;通知/分享链接也基于它 |
| `DEFAULT_ORGANIZATION_ID` | `00000000-0000-0000-0000-0000000000a1` | 与 `dev_bootstrap` 固定 org 对齐;缺了新建用户绑不上组织、`require_system_admin` 直接 500 |
| `MINIO_THUMBNAIL_*` | 全部留空 | 留空 = 回落主 MinIO;`MINIO_THUMBNAIL_BUCKET` 默认 `ms-thumbs`,worker 会在同一个 MinIO 自动建桶 |
| `OIDC_PROVIDER` | 不设 | 空 = 纯本地账号密码登录(ADR-0007 默认形态) |

## 5. 首个管理员 → 用户注册管理(这就是要测的主线)

系统里没有"自助注册":账号由系统 admin 在管理后台创建并下发临时密码(ADR-0007 决策 2)。所以顺序是:

1. **dev 通道进第一个管理员** — 开 `http://localhost:5173/ms-static/web/dev-login`,填 `00000000-0000-0000-0000-000000000001`(alice,`dev_bootstrap` 已给她 `organization#admin`)。这条通道只在 `ENV=dev` 生效,生产自动失效。
2. **建真实账号** — 顶栏进 `管理 → 用户`(`/admin/users`)→ 新建本地用户,填**登录名**(拼音/工号)、姓名、邮箱 → 弹窗回显**一次性临时密码**,复制下来。
3. **用真实账号登录** — 换一个浏览器无痕窗口开 `/ms-static/web/login`,用刚才的**登录名 + 临时密码**登录。
   - 这条路径正是 review F2 修的:登录匹配优先级 `username → email → name`,修之前用登录名登录必然 401。
4. **强制改密** — 登录后被强制跳 `/change-password`;此时任何其它接口都会 403(review F15 的后端拦截),改完密码才放行。
5. **用户组** — `管理 → 用户组`(`/admin/groups`)建组、加人;组成员关系直写 OpenFGA tuple,建完可以在项目成员抽屉里按"组"授权。
6. **禁用/启用** — 禁用会撤掉该用户全部 tuple 且**立即下线**(review F5);重新启用会按 `group_memberships` 把组 tuple 重建回来(review F6)。这两条值得实测一遍。

## 6. 上传 / 下载 验收清单

| # | 动作 | 预期 | 挂了先看 |
| --- | --- | --- | --- |
| 1 | 首页看到 `dev-project`(dev_bootstrap 建的) | 项目卡有 admin 头像 | OpenFGA model 没 push / STORE_ID 不对 |
| 2 | 进项目 → 普通 folder → 拖一张 jpg 上传 | 进度条走完,列表出现该文件 | 浏览器 Network 看 PUT 到 MinIO 是否 403(`MINIO_ENDPOINT_PUBLIC` 或 CORS) |
| 3 | 等几秒刷新 | 出现缩略图 | worker 没起 / `arq` 进程日志;`ms-thumbs` 桶是否自动建出来 |
| 4 | 上传一个 mp4 | 也出缩略图(抽首帧) | `ffmpeg` 是否在 PATH(容器镜像自带;原生方案本机已有) |
| 5 | 上传 >100MB 大文件 | multipart 分片,进度不卡 | `complete_upload` 的 parts 清洗;必要时看 ms-api 日志 |
| 6 | 选中文件 → 下载 | 浏览器直接下到本地 | presigned GET 的 host 同 #2 |
| 7 | 选中文件 → 打标签 + 写备注 | 保存成功 | — |
| 8 | 顶栏 ⌘K / `/search?q=标签词` | 命中刚打的标签 | **这是 review F1 的回归点**:修好后正常;若 500 说明 0011 迁移没跑或 `ms_labels_text()` 函数不在 |
| 9 | 敏感目录:用 bob(`...0002`)去看 | 看不见、搜不到(存在性零泄露) | 这是权限模型的硬验收 |
| 10 | alice 邀请 bob 进敏感目录 | bob 收到应用内通知(铃铛),可见可下 | 通知是 BackgroundTask,失败只 log,看 ms-api 日志 |

## 7. 已知坑速查

- **登录成功却回到登录页** → `SESSION_COOKIE_SECURE` 没改 `false`。
- **页面全空、没有报错** → OpenFGA model 没推进 store,或 `OPENFGA_STORE_ID` 写错;所有 `check` 恒 false 但不报错。
- **上传 403 / SignatureDoesNotMatch** → `MINIO_ENDPOINT_PUBLIC` 与浏览器实际访问的 host 不一致(P-10)。
- **搜索 500** → 0011 迁移没跑成功(需要 `ms_labels_text()` IMMUTABLE 包装函数,见 review §R1)。
- **`alembic upgrade head` 报 `functions in index expression must be marked IMMUTABLE`** → 还在用未修复的 0011。
- **`ValueError: the greenlet library is required`** → 依赖没带 `sqlalchemy[asyncio]`(macOS arm64 不会自动装 greenlet)。
- **`ImportError: ... socksio ...`** → shell 里有 `ALL_PROXY`,httpx 走 SOCKS;装 `httpx[socks]` 或跑测试前 `unset ALL_PROXY HTTPS_PROXY`。
- **migration 链顺序反直觉** → `0006→0007→0008→0010→0009→0011`(0009 是后补的,`down_revision` 指向 0010)。链是单头能跑,别按文件名顺序读。
- **改了 `.env` 没生效(容器)** → `docker compose up -d --force-recreate ms-api`,`docker restart` 不重读 env_file。

## 8. 建议顺手做的两件事

1. **`scripts/local_up.sh`** —— 把 §2 或 §3 的步骤(建 store + 推 model + migrate + seed + 打印入口 URL)收成一条命令。现在每次重来都要手抄 OpenFGA store id,是最容易出错的一步。
2. **`scripts/set_password.py`** —— 给指定 user 设密码 / 清 `must_change_password`。现在想让一个 seed 用户走真实登录流程,只能先用 dev 通道进管理后台建号;有这个脚本可以直接把 alice 变成可密码登录的账号,e2e 脚本也能用。
