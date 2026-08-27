# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 当前方向(2026-08,先看这节)

- **已弃用飞书**(ADR-0007):身份 / 组织 / 通知全部自建。本地账号密码登录、应用内用户组管理后台、应用内通知中心
  已 ship;`feishu-integration/` 日落(archival,不删目录),`rushes-spec/feishu/contracts/` 废止。
- **生产改局域网部署**,按"可完全离线运行"设计;存储分层见 ADR-0008(SSD 放 PG / 缩略图,HDD 放原片)。
- **产品重心**:储存 / 下载 / 分享方便 + **标签盲搜**;权限体系 v4 保留但最小使用,不再追加投入。
- 下面各节描述的是**当前代码状态**;与飞书相关的历史描述已全部移除,遇到疑似飞书残留(除 `users.feishu_*` 只读列)
  按 bug 处理。

## 仓库性质

多项目 monorepo,三个顶层目录边界分明:

| 目录 | 内容 | 归属 |
| --- | --- | --- |
| `material-storage/` | 主产品:医美素材库(`api/` FastAPI + `web/` React + `poc/` 依赖) | material-storage agent |
| `feishu-integration/` | 飞书桥接服务(独立 FastAPI + Caddy + systemd) | **feishu agent 专属,material-storage agent 不在此提交** |
| `rushes-spec/` | 方案 / ADR / ROADMAP / 运维手册 / 协作规则(纯文档) | 共同维护 |

构建、测试、依赖配置全部收敛在各项目目录内,仓库根只放 `README.md` / `.gitignore` / `.github/`。

**`rushes-spec/` 是权威事实源,不是历史归档。** 改 material-storage 代码前按需读:

- `rushes-spec/material-storage/ROADMAP.md` — 当前迭代 + **已知坑清单**(每个坑标了引入的 PR 号,遇到怪行为先搜这里)
- `rushes-spec/material-storage/ops-manual.md` — server2 运维、部署、排查 cheat sheet
- `rushes-spec/material-storage/permissions-model-v4.md` — 改任何权限代码前必读
- `rushes-spec/material-storage/COLLABORATION.md` — issue lifecycle、tester 反馈渠道
- `rushes-spec/material-storage/local-dev-runbook.md` — **从零把整套跑起来**(shserver 验证机,含 seed / 隧道 / 踩坑速查)
- `rushes-spec/material-storage/research/review-2026-08-09-wave1-2.md` — 2026-08 那批改动的深度 review(F1–F18 / R1–R4),
  「仍然开着的」一节是当前未修项
- `rushes-spec/material-storage/decisions/` — ADR;**0007(弃飞书自建身份)/ 0008(存储分层)是当前方向的依据**
- `rushes-spec/feishu/contracts/` — 与飞书 bridge 的历史契约,**已随 ADR-0007 废止**

## 常用命令

### API(`material-storage/api/`,uv + Python 3.12)

```bash
uv sync
uv run uvicorn app.main:app --reload          # :8000
uv run ruff check .
uv run mypy app                               # strict 模式
uv run alembic upgrade head
```

### Web(`material-storage/web/`,pnpm + Vite)

```bash
pnpm install
pnpm dev        # :5173/ms-static/web/,proxy /api + /ms-static → localhost:8200
pnpm build      # 产物直接输出到 ../api/app/static/web/(不是本地 dist/)
pnpm lint
```

`pnpm dev` 的 proxy 指向 **8200**,即 docker-compose 暴露的 ms-api 端口。裸跑 `uvicorn` 是 8000,两者不通 —— 本地全栈联调走 `docker compose up -d`。

### 测试

`tests/test_healthz.py` 和 `test_db_schema.py` 是可独立跑的 smoke test。`test_v4_permissions.py` 是**集成测试,必须在 ms-api 容器内跑**,依赖已 seed 的 demo 数据(user/project UUID 在测试文件里 hardcode)+ 已 push 的 OpenFGA model:

```bash
# 容器内(server2 或本地 compose)
docker exec ms-api pytest tests/ -v
docker exec ms-api pytest tests/test_v4_permissions.py -k "test_fmt_subject" -v   # 单个 test
```

注意 `force-recreate` 后容器内 `pip install` 的 pytest 等 dev 依赖会丢,需重装。

**两个 seed 脚本用途不同,集成测试前置是前者**:

| 脚本 | 建什么 | 谁需要 |
| --- | --- | --- |
| `scripts/seed_demo_data.py` | 3 项目 / 40 folder / 69 assets + 契约账号 **Evan**(`3f1b659e-…`,org admin)/ **outsider**(`…0aa`) | **集成测试的前置**:`test_v4_permissions` / `test_directory` / `test_search_labels` 的 hardcode UUID 全来自它 |
| `scripts/dev_bootstrap.py` | 1 项目 / 2 folder + alice(`…0001`)/ bob(`…0002`) | UI 手工验证 |

只跑 `dev_bootstrap` 的话集成测试会**整片 401「用户不存在」**。两者都幂等。
跑测试前先 `docker compose exec -T ms-redis redis-cli FLUSHALL` 清登录限流锁,否则 rate_limit 用例会把 IP 锁掉、
后续登录测试全 429 假红。

完整的"从零跑起来"步骤见 `rushes-spec/material-storage/local-dev-runbook.md`(验证机 shserver,Ubuntu + docker)。

### 部署 A:server2 dev(`8.156.34.238`,tester 入口)

```bash
cd material-storage/api && bash scripts/deploy_server2.sh
MAINTENANCE_ISSUES="101 104" bash scripts/deploy_server2.sh   # 前端弹 modal 告知 tester 本次修了什么
```

脚本一条龙:build web → 推 maintenance banner → rsync → compose up --build → alembic → seed → e2e → 撤 banner。step 6/7/8 的 ⚠ 是已知非阻塞失败,只关心**新出现**的红色 ✗。

- **默认不覆盖远端 `.env`**,只有 `INIT_ENV=1` 才重写。远端 `.env` 是手工调过的真值,脚本 heredoc 里的是占位符。
- 改 `.env` 后必须 `docker compose up -d --force-recreate ms-api`,`docker restart` 不重读 env_file。
- `.py` 和前端产物都是 bind mount,rsync 后立即生效,不需要 rebuild。

### 部署 B:shserver 验证机(跑集成测试 / 功能验收用)

Ubuntu + docker,与内网生产同构,是**跑全量容器测试的地方**(开发机若是 macOS 则跑不了:无容器运行时,
且 arm64 上 `sqlalchemy` 不自动带 greenlet)。完整步骤见 `rushes-spec/material-storage/local-dev-runbook.md`,
浏览器经 ssh 隧道访问(不开安全组)。

### 部署 C:内网生产(2026-08-27 已首次落地)

ADR-0008 的分层已在内网机实跑通:NVMe 挂元数据/缩略图(`MS_PG_DATA_DIR` / `MS_REDIS_DATA_DIR` /
`MINIO_THUMBS_DATA_DIR`),机械盘挂原片(`MINIO_DATA_DIR`),全部由 `.env` 插值决定,代码零感知。

**开第一个能登录的账号**(新机器绕不过去的一步):`ENV=production` 下 `X-User-Id` 通道失效,
而 seed 脚本只建用户不设密码 —— 用 `scripts/set_initial_admin.py`:

```bash
docker compose exec ms-api python -m scripts.set_initial_admin admin \
    --create --name "系统管理员" --grant-org-admin      # 生成临时密码并打印
```

**同机跑多套环境**(如 dev + prod 并存)必须三层隔离,少一层就会互相接管容器:
`COMPOSE_PROJECT_NAME` + `container_name` 后缀 + `ports` 的 **`!override`**
(compose 对列表默认是合并而非替换,不加就端口冲突)。反代若非 80 端口,nginx 还需
`absolute_redirect off`,否则 302 会丢掉端口把用户弹到另一套环境。

**仍未做**:① 物化 department 存量授权 → ② 跑 `scripts/migrate_subjects_to_uuid.py`
→ ③ 实测 `backup_prod.sh --mirror` 的 HDD 路径。见 ops-manual §10。

## 架构要点(跨文件才看得出来的)

### 服务实例走 `app.state`,不是模块级单例

`app/main.py` 的 lifespan 里构造 `permissions` / `presign` / `auth` / `local_auth` / `arq_pool` / `redis` 挂到 `app.state`;router 一律通过 `app/deps.py` 的 `get_permissions(request)` 等取。新增外部依赖时照此模式接线,不要在 module 顶层建 client。

### 权限:OpenFGA ReBAC + 系统 admin 直通,两者必须成对出现

权限判定的标准形态是:

```python
allowed = is_system_admin or await permissions.check(...)
```

`get_is_system_admin`(`deps.py`)返回 bool 而不抛 403,因为**系统 admin 在所有 project/folder/asset 上一律视为有权限**,而 OpenFGA model 并不自动蕴含这层关系。改任何权限相关代码时,一次 grep 所有 `permissions.check` **和** `list_objects` 调用点 —— 遗漏 `list_objects` 会造成"有权限但列表里看不见"。

三档守门 dependency,别混用:

- `get_current_user` — 仅认证
- `require_admin` — org admin **或**任意 project admin
- `require_system_admin` — 仅 `organization#admin`(建项目、`/admin/*` 全部走这个)

### OpenFGA model 的源文件在 poc 目录

model 源是 `material-storage/poc/openfga/store.fga.yaml`(`poc/` 大部分已废弃,但 `minio/` 和 `openfga/` 仍是活依赖)。**改了 yaml 必须 push 到 store**,否则 live 行为和文件不一致:

```bash
cd material-storage/api && bash scripts/openfga_write_model.sh
ssh root@8.156.34.238 'docker restart ms-api ms-worker'   # .env 未固定 MODEL_ID 时自动取 latest
```

加新 relation 零风险;改 relation 名是 breaking(老 tuple 失效);给已有 relation 加 condition 需 verify 存量 tuple。**判断存量影响一律查 OpenFGA store,不要查 `audit_events`** —— 两者会不一致。

subject 一律是**本地身份**(#148 起,不再用飞书 ID):`user:<users.id UUID>` / `group:<本地 groups.id UUID>#member` / `organization:<tenant_key>`。`fmt_subject()` 负责 `#member` 后缀,其 Literal 已收窄到 `user` / `group`。**department 轴已废弃**(#154 删除写入路径;存量 tuple 未迁移,留给离职清理,判断影响一律查 OpenFGA store)。

### 认证:本地账号密码(ADR-0007 起,飞书 OIDC 已下线)

1. 生产:**本地账号密码登录** `POST /api/v1/auth/local/login` → cookie `ms_session`(HS256 JWT)。argon2id 哈希、
   Redis 双维限流(per IP + per username,5 次失败锁 15 分钟)。登录名匹配优先级 **username → email(含 @)→ name 兜底**,
   全部忽略大小写;任一维度命中多行则拒绝(防重名锁死)。
2. 本地 dev:`X-User-Id` header,**仅 `env == "dev"` 生效**,前端在 `/ms-static/web/dev-login` 切换。
3. OIDC 只保留**一层 provider 配置**(`settings.oidc_provider`,dict,默认空 = 纯本地登录)。hand-rolled httpx,
   **未做 id_token 校验 / PKCE** —— 是"留口",不是"就绪",接真 IdP 前必须补齐。

`CurrentUser` 只有 `id`(SQL UUID,同时做 FK 和 OpenFGA subject)+ `name`;`subject` property 给 `user:<uuid>`。
飞书 open_id **不再进 session**,`users.feishu_open_id` / `feishu_union_id` 列按 ADR-0007 保留只读作历史对照。

`get_current_user` 每请求查一次库(单条 select 取 `id/name/is_active/must_change_password/password_hash`),因为:
- **禁用必须立即下线**(review F5):`is_active=false` 直接 401,不能等 JWT 7 天过期;
- **强制改密后端拦截**(review F15):`must_change_password` 且已设密码时,除 `me`/`change_password`/`logout` 外一律 403。
两者当初是两次查询,已合并成一次(review R3),别再拆回去。

### 前端由后端发布,路径有内外之分

`pnpm build` → `api/app/static/web/` → ms-api 用 StaticFiles mount 在 `/static/web`;nginx rewrite `/ms-static/(.*)` → `/static/$1`,浏览器看到的是 `/ms-static/web/`,与 `BrowserRouter basename` 一致。

**任何 307 redirect 必须指向 public 路径 `/ms-static/...`**,泄漏内部 `/static/...` 会让 SPA basename 错位白屏。`main.py` 里那两个手写 SPA route(catch-all + 无尾斜杠 root)就是为此存在,顺序在 `mount("/static")` 之前,不要调换。

### 其他约定

- `audit.write()` 内部自带 commit,调用方不要再 commit。
- 用户可见的 `event_type` / `action` / `target_type` 文案统一过 `web/src/lib/labels.ts` 的 `tlabel()`;后端契约、CSV 导出、ID 保持英文原样。后端新增 event_type 时顺手补 mapping(缺 key 不报错,回落 raw token)。
- 缩略图走 short presigned URL,**不过 OpenFGA enforce**(已决策:1024px 模糊,信息密度低)。
- `sensitive_folder` 的 `can_view` **不含 admin** —— parent project 的 admin 不隐式可见,创建时须显式给 creator `invited_downloader`。
- 前端每个 endpoint 一个 react-query hook,集中在 `web/src/api/hooks.ts`;axios 的 cookie/header 注入在 `web/src/api/client.ts`。
- **通知中心**(#153):写入口在 `services/notifications.py`,由 routers 流程主体注册 BackgroundTask(不在已删除的
  notify 文件里)。失败只 log 不影响主流程;SMTP 留空 = 真 no-op。分享已是纯链接,**没有分享通知**。
- **标签盲搜**(#151 + review F1/R1):`GET /assets/search` 跨 folder 搜 filename / user_labels / notes。
  标签模糊分支必须用 `func.ms_labels_text(...)`,**不能**用裸 `array_to_string` —— 后者在 PG 是 STABLE,
  既进不了索引表达式,查询侧写法不一致还会让 GIN 索引不命中。非系统 admin 先 `list_objects(can_view)` 取可达
  folder 集合再 `folder_id IN`,sensitive 素材存在性零泄露(这是硬验收)。已知未修:`list_objects` 有返回上限,
  folder 极多时结果会**静默截断**(review F9)。
- **migration 链顺序反直觉**:`0006→0007→0008→0010→0009→0011`(0009 是后补的,`down_revision` 指向 0010)。
  链是单头、能跑,**别按文件名顺序读**。并行开发时两个分支各写 migration 会撞 revision / 造双 head,
  merge 后记得改后合入那个的 `down_revision`。

## Git 与协作

- **本仓库公开。** `.env`、飞书 app secret、真实顾客/员工数据、医美客户照片姓名手机一律不进 commit、issue、PR、日志、截图。
- 提交身份必须是**仓库级**配置的 `Evan <kevinfitzroy715@gmail.com>`,不能回退到全局邮箱。第一次 commit 前先确认 `git config user.email`。
- **不直推 `main`**。feature branch → PR → squash merge。远端走 SSH alias `kevinfitzroy.github.com`。
- Issue 走 `.github/ISSUE_TEMPLATE/` 三个模板:`bug.yml` / `feature.yml` / `frontend-feature.yml`。
- 工作区本地还有 `CLAUDE.md` / `git.md` / `refs/` 不进本仓库,写文件前先确认目标路径在 `rushes-lab/` 内。
