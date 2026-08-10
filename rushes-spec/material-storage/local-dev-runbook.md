# 开发/验证机跑起来 runbook(无飞书 · 可测上传/下载/建号)— shserver 版

> 目标:在 **shserver**(阿里云上海 `8.153.13.86`,Ubuntu 24.04)上把完整 web 应用跑起来,能实测 **上传 / 下载 / 用户注册管理 / 登录改密 / 盲搜**,并跑通仓库全部容器集成测试。
> 背景变更(2026-08-10):**不再在 macOS 本地跑** —— mac 的兼容性问题太多(arm64 greenlet、无容器运行时、socksio 代理、brew 版差异,见 review R2),shserver 与内网生产同为 Linux + docker,行为一致。
> 前提:ADR-0007 之后已无飞书依赖 —— 登录走本地账号密码,不需要任何公网服务。
> 最后更新:2026-08-10。配套:[ops-manual](./ops-manual.md)(内网生产)、[ROADMAP](./ROADMAP.md)。

## 0. 先看这三条

1. **0011 migration 的表达式索引已按 review R1 修复并合入 main**:用 IMMUTABLE 包装函数 `ms_labels_text()` 建 GIN 索引(裸 `array_to_string` 是 STABLE,PG 直接拒绝 `functions in index expression must be marked IMMUTABLE`)。**代码在 main 上就是对的,直接 `alembic upgrade head` 即可**;查询侧 `assets.py` 同步用 `func.ms_labels_text(...)`(不一致索引不命中)。
2. **`.env.example` 可以直接 `cp` 就起**(补了 `WEB_APP_BASE_URL` / `DEFAULT_ORGANIZATION_ID` 两个必填项;之前照抄会直接 ValidationError)。
3. **浏览器访问走 ssh 隧道**(见 §2.0),不需要给阿里云安全组开任何业务端口 —— `MINIO_ENDPOINT_PUBLIC` 填 `http://localhost:6100` 即可与隧道内浏览器视角一致,presigned 签名 host 不会错。

## 1. 选哪条路

| | 方案 A:docker compose(推荐) | 方案 B:全原生 apt |
| --- | --- | --- |
| 需要装 | **已装好**:docker 29.7 + compose v5.4(阿里云源)+ 镜像加速器 | postgresql@16 · minio · openfga(手动装二进制) |
| 与生产一致 | ✅ 就是内网要用的那套 compose | ⚠️ 组件版本/拓扑自己维护 |
| 能跑仓库的全部集成测试 | ✅ `docker exec ms-api pytest tests/ -v` | ❌ 部分用例假设容器名 |
| 磁盘/内存 | 镜像 + 构建 ~4G,内存 7G 够 | 原生进程更省 |
| 适合 | 要跑那 60+ 个集成测试、行为对齐内网 | 只想起个 API 看看 |

**推荐 A。** shserver 上 docker 已装好(2026-08-10,阿里云 docker-ce 源 + DaoCloud 镜像加速器),和内网生产同一套 compose,容器集成测试也能全量跑 —— 这正是 review handoff 排第一的待办。

## 2. 方案 A:shserver docker compose

### 2.0 隧道(先开这个,浏览器全走它)

```bash
# mac 本地执行;把业务端口全部映射到本地,浏览器访问 http://localhost:5173
ssh -L 6100:localhost:6100 -L 6101:localhost:6101 -L 8089:localhost:8089 \
    -L 5173:localhost:5173 -L 8200:localhost:8200 shserver
```

> 为什么:阿里云安全组只开了 22;业务端口走隧道不用开安全组,`MINIO_ENDPOINT_PUBLIC` 也就能安心填 `localhost`(presigned URL 按浏览器实际访问的 host 签名,P-10 老坑)。

### 2.1 同步代码(shserver 上的工作目录 `/home/ecs-user/ms`)

```bash
# mac 本地,从 rushes-lab 主 worktree
rsync -az --delete -e ssh --exclude '.git' --exclude '.env' --exclude 'node_modules' \
    --exclude 'uv.lock' --exclude '__pycache__' --exclude 'static/web' \
    material-storage/ shserver:/home/ecs-user/ms/
```

### 2.2 起依赖栈(MinIO + OpenFGA + nginx)

```bash
ssh shserver 'cd /home/ecs-user/ms/poc/minio && docker compose up -d pigsty-minio poc-minio-thumbs poc-openfga-db poc-openfga-migrate poc-openfga poc-nginx'
```

- MinIO S3 API → `localhost:6100`,Console → `localhost:6101`(默认账号见 compose,本地不改也行)
- OpenFGA HTTP → `localhost:8089`,Playground → `localhost:3001`
- nginx → `localhost:80`(把 `/ms-static/*` 转 ms-api、`/ms-thumbs/*` 转缩略图 MinIO)
- `poc-console` / `poc-presigner` / `poc-webhook` / `seafile` 本地不需要,别起

### 2.3 建 OpenFGA store + 推 model(**漏了这步所有权限判定恒 false**)

```bash
ssh shserver 'cd /home/ecs-user/ms/api
# 1) 建 store,拿 STORE_ID
STORE_ID=$(curl -s -X POST http://localhost:8089/stores \
  -H "content-type: application/json" \
  -d "{\"name\":\"material-storage-dev\"}" | python3 -c "import sys,json;print(json.load(sys.stdin)[\"id\"])")
echo "STORE_ID=$STORE_ID"
# 2) 从 store.fga.yaml 抽 model DSL
python3 -c "import yaml;print(yaml.safe_load(open(\"../poc/openfga/store.fga.yaml\"))[\"model\"])" > /tmp/model.fga
# 3) DSL → JSON 并写入 store(用官方 CLI 镜像,免装二进制)
MODEL_JSON=$(docker run --rm -i openfga/cli model transform --input-format fga < /tmp/model.fga)
curl -s -X POST "http://localhost:8089/stores/$STORE_ID/authorization-models" \
  -H "content-type: application/json" -d "$MODEL_JSON" | head -c 200'
```

> `.env` 不固定 `OPENFGA_MODEL_ID` 时 ms-api 自动取 store 的 latest model,所以只要写进去就行。

### 2.4 写 `api/.env`

```bash
ssh shserver 'cd /home/ecs-user/ms/api
cp .env.example .env'
```

然后按 §4 的表改这几项(容器内互相用容器名):

```
MINIO_ENDPOINT_INTERNAL=http://pigsty-minio:9000
MINIO_ENDPOINT_PUBLIC=http://localhost:6100      # ← 浏览器视角(隧道),必须可达
MINIO_DEFAULT_BUCKET=ms-dev
OPENFGA_API_URL=http://poc-openfga:8080
OPENFGA_STORE_ID=<2.3 拿到的>
SESSION_COOKIE_SECURE=false                      # ← http 隧道,不改的话 cookie 永远存不下
SESSION_JWT_SECRET=<openssl rand -hex 32>
WEB_APP_BASE_URL=http://localhost:5173/ms-static/web/
```

### 2.5 起 api 栈 + 建库 + 灌种子

```bash
ssh shserver 'cd /home/ecs-user/ms/api
docker compose up -d --build          # ms-db / ms-redis / ms-api / ms-worker
docker compose exec ms-api alembic upgrade head
docker compose exec ms-api python -m scripts.seed_demo_data   # ★ 集成测试的前置契约
docker compose exec ms-api python -m scripts.dev_bootstrap'
```

**两个 seed 都要跑,用途不同**(踩过的坑):
- `seed_demo_data.py` —— **集成测试的前置契约**:建 3 项目 / 40 folder / 69 assets / 真 user Evan(`3f1b659e-9ef1-4e65-aa03-4407ad7bcfc4`,org admin)/ fake outsider(`...0aa`)。`test_v4_permissions` / `test_directory` / `test_search_labels` 的 hardcode UUID 全部来自它。**只跑 dev_bootstrap 的话这些测试全 401「用户不存在」**。
- `dev_bootstrap.py` —— 最小 demo:alice(`...0001`)/ bob(`...0002`)/ 1 项目 / 2 folder,给 UI 手工验证用。

`dev_bootstrap` 输出里记下 `ADMIN_USER_ID`(固定 `00000000-0000-0000-0000-000000000001`,alice = org admin = 系统 admin)。

> seed 幂等,重跑安全;但改过 seed 后重跑测试前 `docker compose exec -T ms-redis redis-cli FLUSHALL`(清登录限流锁,否则 rate_limit 用例先锁 IP,后续登录测试全 429 假红)。

### 2.6 前端

```bash
ssh shserver 'cd /home/ecs-user/ms/web
pnpm install && pnpm dev'      # :5173/ms-static/web/,proxy /api → localhost:8200
```

浏览器(隧道已开)开 **http://localhost:5173/ms-static/web/dev-login**。

### 2.7 跑全量容器集成测试(handoff 排第一的待办)

```bash
ssh shserver 'docker exec ms-api pytest tests/ -v'
```

> 全部集成测试依赖容器内的 seed 数据 + 已 push 的 OpenFGA model;`force-recreate` 后容器内 dev 依赖会丢,需重装。

---

## 3. 方案 B:全原生(shserver apt,不装容器)

```bash
sudo apt-get install -y postgresql-16 redis-server ffmpeg nginx
sudo systemctl start postgresql redis-server
# MinIO 二进制:github.com/minio/minio/releases 下载到 /usr/local/bin
# OpenFGA 二进制:github.com/openfga/openfga/releases + fga CLI
```

业务库 / store+model / `.env`(全 localhost) 与 §2 同构,把容器名换成 localhost、`docker compose exec` 换成 `uv run`。OpenFGA 用本地 PG 做 datastore(重启不丢 store)。

> 方案 B 不需要 nginx:vite dev server 自己挂在 `/ms-static/web/` 并把 `/api` 代理到 8200,和 `BrowserRouter basename` 天然对得上。想验证"构建产物由 ms-api 发布"的生产形态时才需要 nginx 做 `/ms-static/* → /static/*` 的 rewrite。

---

## 4. `.env` 关键项(两方案通用,踩过的坑都在这)

| key | 值 | 为什么会踩 |
| --- | --- | --- |
| `ENV` | `dev` | 不是 `dev` 时 `X-User-Id` 开发通道直接拒绝,首个管理员没法登录 |
| `DB_URL` | `postgresql+asyncpg://msuser:mspass@ms-db:5432/material_storage` | **容器模式必须容器名 `ms-db`**;`.env.example` 默认 `localhost` 是宿主机直跑写法,照抄的话 `alembic upgrade head` 报 `Connect call failed (127.0.0.1, 5432)` |
| `REDIS_URL` | `redis://ms-redis:6379/0` | 同上,容器名 `ms-redis`,不是 localhost |
| `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` | `minioadmin` / `minioadmin-poc-2026`(与 poc 栈 MinIO root 一致) | `.env.example` 默认是老 PoC 的 `alice` 凭据,与实例 root 不匹配 → dev_bootstrap 报 `HeadBucket 403 Forbidden` |
| `SESSION_COOKIE_SECURE` | `false` | 默认 `true`;http(隧道)下浏览器**静默丢弃** Set-Cookie,表现是"登录成功但立刻又跳登录页" |
| `MINIO_ENDPOINT_PUBLIC` | 浏览器真正能访问的 host:port(隧道下 = `http://localhost:6100`) | presigned URL 按这个 host 签名,写错 → 上传/下载 403 SignatureDoesNotMatch(P-10 老坑) |
| `MINIO_ENDPOINT_INTERNAL` | 容器名(poc 栈里是 `pigsty-minio`/`poc-pigsty-minio`,以 compose 实际服务名为准) | ms-api/worker 服务端调用用 |
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
| 4 | 上传一个 mp4 | 也出缩略图(抽首帧) | `ffmpeg` 是否在容器镜像内(自带) |
| 5 | 上传 >100MB 大文件 | multipart 分片,进度不卡 | `complete_upload` 的 parts 清洗;必要时看 ms-api 日志 |
| 6 | 选中文件 → 下载 | 浏览器直接下到本地 | presigned GET 的 host 同 #2 |
| 7 | 选中文件 → 打标签 + 写备注 | 保存成功 | — |
| 8 | 顶栏 ⌘K / `/search?q=标签词` | 命中刚打的标签 | **review F1/R1 的回归点**:修好后正常;若 500 说明查询侧没用 `ms_labels_text()` 或索引没建 |
| 9 | 敏感目录:用 bob(`...0002`)去看 | 看不见、搜不到(存在性零泄露) | 这是权限模型的硬验收 |
| 10 | alice 邀请 bob 进敏感目录 | bob 收到应用内通知(铃铛),可见可下 | 通知是 BackgroundTask,失败只 log,看 ms-api 日志 |

## 7. 已知坑速查

- **登录成功却回到登录页** → `SESSION_COOKIE_SECURE` 没改 `false`。
- **页面全空、没有报错** → OpenFGA model 没推进 store,或 `OPENFGA_STORE_ID` 写错;所有 `check` 恒 false 但不报错。
- **上传 403 / SignatureDoesNotMatch** → `MINIO_ENDPOINT_PUBLIC` 与浏览器实际访问的 host 不一致(P-10);隧道下必须填 `http://localhost:6100`。
- **`alembic upgrade head` 报 `functions in index expression must be marked IMMUTABLE`** → 代码不是最新 main(0011 的 R1 修复没在);或数据库在旧 revision 上重放旧 0011。
- **`docker exec ms-api pytest` 报 ImportError / 缺包** → `force-recreate` 后容器内 dev 依赖丢了,`docker compose exec ms-api pip install -r requirements-dev.txt`(或镜像重建)补上。
- **拉镜像慢/失败** → 镜像加速器已配(DaoCloud);仍失败检查 `/etc/docker/daemon.json` 的 `registry-mirrors`。
- **`ImportError: ... socksio ...`** → shell 里有 `ALL_PROXY`,httpx 走 SOCKS;装 `httpx[socks]` 或跑测试前 `unset ALL_PROXY HTTPS_PROXY`。
- **migration 链顺序反直觉** → `0006→0007→0008→0010→0009→0011`(0009 是后补的,`down_revision` 指向 0010)。链是单头能跑,别按文件名顺序读。
- **改了 `.env` 没生效(容器)** → `docker compose up -d --force-recreate ms-api`,`docker restart` 不重读 env_file。
- **磁盘紧张** → 40G 盘,镜像 + 构建后剩 ~10G;定期 `docker system prune`;大镜像构建失败先看 `df -h /`。
- **shserver 重启后容器没起来** → docker 已 `systemctl enable`;`docker compose up -d` 幂等,重跑一遍即可。

## 8. 建议顺手做的两件事

1. **`scripts/local_up.sh`** —— 把 §2 的步骤(建 store + 推 model + migrate + seed + 打印入口 URL)收成一条命令。现在每次重来都要手抄 OpenFGA store id,是最容易出错的一步。
2. **`scripts/set_password.py`** —— 给指定 user 设密码 / 清 `must_change_password`。现在想让一个 seed 用户走真实登录流程,只能先用 dev 通道进管理后台建号;有这个脚本可以直接把 alice 变成可密码登录的账号,e2e 脚本也能用。
