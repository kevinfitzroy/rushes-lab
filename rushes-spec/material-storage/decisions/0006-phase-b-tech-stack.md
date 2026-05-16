# ADR-0006 — Phase B 技术选型(权限引擎 / 业务后端 / 前端 / 数据库 / 飞书集成 / Worker)

- Status: **proposed**(2026-05-16 起草)
- Date: 2026-05-16
- Builds on: [ADR-0005 — 去 Seafile + MinIO + 自研业务 UI](./0005-drop-seafile-middle-layer-minio-only.md)
- Related:
  - [ADR-0001 — 不自研通用 Web UI](./0001-no-full-custom-web-ui.md)(业务 UI 范围)
  - [ADR-0002 — 飞书通讯录作身份源](./0002-feishu-contacts-as-identity-source.md)(用户体系来源)
  - [feishu ADR-0002](../../feishu/decisions/0002-bridge-as-oidc-provider.md)(SSO 路径)
  - [PoC openfga](../../../material-storage/poc/openfga/)(OpenFGA model 28/28 通过)
  - [PoC pigsty-minio](../../../material-storage/poc/minio/)(存储 / uppy / Console)

---

## 决策结论(一页)

| 决策点 | 选型 | 核心理由 |
| --- | --- | --- |
| **权限引擎** | [OpenFGA](https://openfga.dev) v1.15+,Apache 2.0,CNCF | PoC 28/28 verified;ReBAC + conditional tuple 直接解 §11.2 Gap 1/5 |
| **业务后端 framework** | **Python FastAPI** + uvicorn + Pydantic v2 | 与现有 PoC(presigner / webhook)+ feishu bridge 全部 Python,生态一致 |
| **业务后端数据库** | **PostgreSQL 16** | audit-schema(PR #30)+ 业务元数据 + OpenFGA 后端共用 PG instance |
| **业务前端 framework** | **React 18 + TypeScript + Vite + Ant Design Pro** | 中后台业务 UI 主流生态,Ant Design 中文+企业级 component 多 |
| **前端入口形式** | **双轨**:① 飞书 H5 应用(主,飞书工作台一键开)② 独立 Web URL(备,运维 / 外部 / 公网)| 飞书 SSO 透明 + 卡片推送 + 用户已在飞书 |
| **飞书 SDK** | [`larksuite/oapi-sdk-python`](https://github.com/larksuite/oapi-sdk-python)(已用)| bridge 已集成 |
| **业务后端 ↔ MinIO** | **boto3**(boto3 ≥ 1.34,asyncio 用 aioboto3) | sigV4 / presigned URL / STS / admin API 全部官方 |
| **旁路 worker queue** | **arq**(Redis 后端,Python asyncio 原生) | 比 Celery 轻量;asyncio 原生与 FastAPI 一致;Redis 已是必备 cache |
| **session / cache** | **Redis 7** | 业务 session + presigned URL 短期黑名单(辅)+ arq queue |
| **OIDC / SSO** | 通过 bridge 复用 MS-FB-004 OIDC(material-storage 作 RP)| ADR-0005 §11.3 接缝,直接复用 |
| **业务 UI 大文件上传** | **uppy v4 + AwsS3 multipart plugin**(已 PoC verified)| 100GB+ ETag verified |
| **音视频处理** | **ffmpeg + Pillow + opencv-headless** | 旁路 worker 内,生成代理版 + 缩略图 + keyframe |
| **部署形态(Phase B)** | docker-compose(单机)| Phase C 评估 k8s |
| **CI / lint / test** | GitHub Actions + ruff + pytest + mypy strict | Python 标准栈 |

---

## 1. 权限引擎:**OpenFGA**

### 1.1 选型理由(PoC verified)

- ✅ **ReBAC 模型**:user × group × organization × project × folder × asset 自然继承关系,DSL 表达比 SQL ACL 简洁 5-10×
- ✅ **Conditional Tuples**(v1.4+):时间限定 grant `current_time < grant_time + grant_duration`,**解 Gap 1**(presigned URL 撤销)— 审批通过的临时 grant 自动过期,无需 cron / 黑名单
- ✅ PoC 28/28 通过,边界条件(grant 起 / 中 / 末 / 过期后)全正确
- ✅ Auth0 / CNCF 沙箱,5.2k stars,月度 release,Apache 2.0
- ✅ 部署轻量(单 binary + PG,~ 130 MB),已加入 `poc/minio/docker-compose.yml`
- ✅ Python SDK 官方:[`openfga/python-sdk`](https://github.com/openfga/python-sdk)

### 1.2 不采纳的替代

| 候选 | 不采纳理由 |
| --- | --- |
| **SpiceDB**(Authzed)| 与 OpenFGA 同源 Zanzibar,功能重叠;Authzed 商业公司主导(license 改风险);OpenFGA 在 CNCF 治理更稳 |
| **Cerbos** | Policy 用 YAML / Rego,**适合无关系的 ABAC**;我们关系多(user-group-project-folder-asset)不适合 |
| **Casbin** | 轻量级,但 ReBAC 弱;时间条件 grant 要手写,不如 OpenFGA 内置 |
| **手写 PostgreSQL ACL 表** | 维护噩梦,关系继承靠 recursive CTE 性能差;边界 case 易漏 |
| **Auth0 / Permit.io / etc. SaaS** | 数据不出公司前提排除 |

### 1.3 部署 footprint

| 容器 | 镜像 | 内存 |
| --- | --- | --- |
| openfga | openfga/openfga:v1.15+ | ~ 50 MB |
| openfga-db | postgres:16-alpine | ~ 80 MB(可与业务 PG 共 instance,不同 database)|

---

## 2. 业务后端 framework:**FastAPI(Python 3.12)**

### 2.1 选型理由

- 现有 PoC(presigner / webhook / feishu bridge)**全部 Python**,生态一致
- FastAPI = 业界标准 async web framework(Pydantic v2 + OpenAPI 自动生成 + 性能优于 Flask/Django REST)
- material-storage agent 在主对话已熟悉 Python 工具链
- 飞书 SDK(larksuite/oapi-sdk-python)+ openfga-sdk + boto3 + ffmpeg-python 全 Python 一线

### 2.2 不采纳的替代

| 候选 | 不采纳理由 |
| --- | --- |
| **Node.js NestJS** | 团队语言切换成本;Python 生态在 audit / AI / data 更强 |
| **Go Echo / Fiber** | 性能更高但开发 velocity 低 |
| **Ruby Rails** | 生态老,审计 / AI / S3 sdk 不如 Python |
| **Django** | 重 + 自带 ORM/admin 增加复杂度;FastAPI 更轻便 |

### 2.3 业务后端结构(skeleton)

```
material-storage/
├── app/
│   ├── main.py                 # FastAPI app + middleware + lifespan
│   ├── settings.py             # Pydantic Settings(env)
│   ├── deps.py                 # DI:db / openfga / feishu / s3 client
│   ├── routers/
│   │   ├── auth.py             # OIDC RP(MS-FB-004 接入)
│   │   ├── projects.py         # CRUD project / assign user
│   │   ├── assets.py           # 浏览 / 上传 presigned / 下载
│   │   ├── approvals.py        # 申请下载敏感 / 收 bridge webhook
│   │   ├── webhooks.py         # MinIO event / bridge approval
│   │   └── admin.py            # admin 后台
│   ├── models/                 # Pydantic schemas(API I/O)
│   ├── db/
│   │   ├── tables.py           # SQLAlchemy 2.x models
│   │   └── migrations/         # alembic
│   ├── services/
│   │   ├── permissions.py      # OpenFGA wrapper
│   │   ├── presign.py          # MinIO presigned URL 签发
│   │   ├── proxy.py            # 敏感目录 stream proxy
│   │   ├── audit.py            # audit 落库(PR #30 修订版 schema)
│   │   └── feishu.py           # 飞书 API 封装
│   └── workers/
│       ├── transcode.py        # arq task:ffmpeg → dataset B
│       ├── thumbnail.py        # 缩略图 / keyframe
│       └── ai_tag.py           # 占位,Phase C
├── pyproject.toml              # uv / hatch / pip-tools
├── alembic.ini
├── docker-compose.yml          # dev(extends ../poc/minio + openfga)
└── README.md
```

---

## 3. 业务前端 framework:**React 18 + TypeScript + Vite + Ant Design Pro**

### 3.1 选型理由

- **React** 中后台业务 UI 主流;招聘 / AI 辅助代码工具(Claude Code / Cursor)支持最好
- **Ant Design Pro** 中文 + 企业级 component 多,中后台模板齐(用户管理 / 角色 / 审批列表 / 文件浏览器);避免重写
- **Vite** 构建 dev 体验 + HMR
- **TypeScript** 配合 Pydantic v2 后端 OpenAPI 生成 client(`openapi-typescript-codegen`)
- 飞书 H5 应用与独立 web URL **共用同一 React build**,不重复维护

### 3.2 不采纳

| 候选 | 不采纳理由 |
| --- | --- |
| Vue 3 + Element Plus | 国内常用但 Ant Design Pro 中后台模板更丰富 |
| Svelte / Solid | 生态 component 不够丰富,需手写多 |
| 纯飞书 H5(无 React framework)| 限于飞书,独立 web 入口不支持 |
| Tauri 桌面 app | Phase B 不必;桌面访问可用 Cyberduck/rclone(ADR-0005 §7.1)|

---

## 4. 前端入口形式:**双轨(飞书 H5 主 + 独立 Web 备)**

### 4.1 飞书 H5(主入口)

- 用户在飞书工作台一键打开,免登录(飞书 SDK + JSSDK 自动 SSO)
- 审批 / 上传成功 / 配额警告 → 飞书 IM 卡片推送(MS-FB-008 契约,待 issue #36)
- 卡片回执直达 material-storage(MS-FB-007 v2)
- 用户不离开飞书 context

### 4.2 独立 Web URL(备)

- 域名:沿用 `rusheslab.taoxiplan.com`(Phase A 已就位,真证书 + nginx 反代)
- 给运维 / 公网用户 / 外部审计访问
- 飞书 SSO 仍走 OIDC(bridge MS-FB-004)

### 4.3 飞书 H5 实施细节

| 项 | 选择 |
| --- | --- |
| 飞书 H5 模式 | "网页应用 / Web App"(后台传 HTTPS URL,飞书 webview 直接打开)|
| 免登录 | 飞书 JSSDK `tt.requestAuthCode()` → bridge 换 OIDC code → token(MS-FB-004)|
| 容器 | 飞书内嵌 webview(Chromium / WKWebView)|
| 卡片推送 | MS-FB-008 契约(feishu agent 起草中,issue #36)|

---

## 5. 数据库:**PostgreSQL 16**

### 5.1 单实例 + 多 database

| Database | 用途 |
| --- | --- |
| `material_storage` | 业务元数据 + audit(PR #30 schema 修订) |
| `openfga` | OpenFGA 权限引擎后端 |

### 5.2 选型理由

- audit-schema 设计已基于 PG(`UNIQUE INDEX` / `JSONB` / `WITH RECURSIVE`)
- 业务元数据 schema 复杂(project / asset / folder / approval / etc.)
- 单实例足够 Phase B(100 人 / 数 TB);Phase C 评估 read replica
- 与 OpenFGA 共用 PG instance(不同 db),减少运维

### 5.3 ORM:**SQLAlchemy 2.x(async)+ alembic**

- Python ecosystem 事实标准
- Pydantic v2 集成顺
- `asyncpg` driver

---

## 6. 旁路 worker queue:**arq(Redis)**

### 6.1 选型理由

| 维度 | arq | Celery | 选 arq |
| --- | --- | --- | --- |
| asyncio 原生 | ✅ | ❌(同步,asyncio 桥适配) | 与 FastAPI 一致 |
| 配置复杂度 | 低 | 高(broker / backend / beat) | arq 单 Redis |
| 性能 / 吞吐 | 中(够用) | 高 | 我们旁路 worker 量级中等 |
| 生态 | 中(GitHub 3k stars) | 高 | arq 够用 |
| 学习曲线 | 极低 | 中 | velocity |

### 6.2 worker 任务清单(对应 §11.2 Gap 8)

- `transcode_proxy_version(asset_id)`:ffmpeg → 720p H.264,写 dataset B
- `generate_thumbnail(asset_id)`:Pillow / opencv keyframe
- `extract_metadata(asset_id)`:ffprobe → 时长 / 分辨率 / 编码
- `ai_tag(asset_id)`:Phase C 占位
- `cleanup_expired_grants()`:**非必需**(OpenFGA conditional 自动失效)— 可选 audit 定时报告

---

## 7. 部署形态:**docker-compose 单机(Phase B)**

### 7.1 components(扩展现有 PoC)

```
现有(PoC):
  poc-pigsty-minio        ← 存储
  poc-nginx               ← 80 path 分发
  poc-console             ← MinIO admin UI
  poc-presigner           ← uppy multipart presigner
  poc-webhook             ← MinIO event receiver(临时,Phase B 整合到业务后端)
  poc-openfga + poc-openfga-db ← 权限引擎

Phase B 新增:
  material-storage-api    ← FastAPI 业务后端
  material-storage-worker ← arq worker(同 image,不同 entrypoint)
  material-storage-db     ← PostgreSQL(业务元数据 + audit)
  material-storage-redis  ← arq broker + cache
  material-storage-web    ← React build,nginx 静态 serve
```

→ 增 4 个 service(api/worker/db/redis),复用 ext nginx + Caddy HTTPS。

### 7.2 不采纳

| 候选 | 不采纳理由 |
| --- | --- |
| **k8s** | Phase B 单机够;k8s 增加运维负担;Phase C 评估 |
| **systemd 直跑(无 docker)** | 与现有 PoC 不一致;build / 升级复杂 |

---

## 8. CI / lint / test:**GitHub Actions + ruff + pytest + mypy strict**

| 工具 | 用途 |
| --- | --- |
| **uv** | 包管理 + venv |
| **ruff** | lint + format(替代 black + isort + flake8) |
| **pytest** + **pytest-asyncio** | 测试 |
| **mypy --strict** | 静态类型 |
| **GitHub Actions** | CI;Phase B 不上 self-hosted runner |

---

## 9. Phase B 实施路径(粗粒度)

### Phase B-1:business backend skeleton(2-3 周)

- FastAPI app + Pydantic v2 settings + lifespan(connect PG / Redis / OpenFGA / feishu)
- alembic migration 0001(基础表:user / project / folder / asset / approval / audit)
- 集成 openfga-sdk 封装 `permissions.py`(`grant_sensitive / check / revoke_user`)
- 集成 boto3 封装 `presign.py`(签 presigned URL)
- OIDC 接 bridge(MS-FB-004 RP)
- 一个 e2e endpoint:`POST /projects/{id}/assets/upload-url` → 签 MinIO presigned PUT URL
- 出口:简单 curl 跑通"创建项目 → 上传(presigned)→ 列资产"

### Phase B-2:权限 + audit + 飞书审批接入(3-4 周)

- 业务权限模型 → OpenFGA tuples(project create 时自动 write `project:X organization org:Y`)
- audit 落库(PR #30 修订:无 Seafile 字段)
- MS-FB-007 v2 webhook handler:收 `metadata.material_storage_ref` → 写 OpenFGA grant + 签 presigned URL + 通知申请人
- 敏感目录代理 stream + 每 chunk check(Gap 1 + Gap 3)
- presigned URL 撤销 black list(辅助,真撤销由 OpenFGA 时间过期)
- 出口:完整"申请→审批→下载敏感"流程跑通

### Phase B-3:业务 UI(4-6 周)

- Vite + React + TS + AntD Pro init
- 飞书 H5 + 独立 web 双入口
- 核心 views:登录 / 项目列表 / 资产浏览(grid + 缩略图)/ 资产详情 / 上传 / 审批申请 / 我的审批 / admin 后台
- uppy v4 multipart 上传(已 PoC verified)
- WebSocket 接 audit 流 + 审批结果通知(MS-FB-008)
- 出口:业务用户走完整流程

### Phase B-4:旁路 worker + 灾备(2-3 周)

- arq + Redis worker
- transcode / thumbnail / metadata extraction(MinIO event 触发)
- dataset B 写专 bucket
- MinIO bucket replication 异地灾备(active-passive)
- 出口:旁路 worker 链路稳定 + 灾备演练

**Phase B 总计:11-16 周(2-4 人月)**,具体取决于人力。

---

## 10. ADR-0005 §11.2 Gap 清单 update(基于本 ADR 选型)

| Gap | 之前状态 | 本 ADR 后 |
| --- | --- | --- |
| **Gap 1** presigned URL 撤销 | 🔴 未规划 | ✅ OpenFGA conditional + 双轨敏感代理(verified PoC) |
| **Gap 2** uppy 大文件 UX | 🟡 选了 uppy | ✅ Phase A.2 已实测 632 MiB / 跨境 |
| **Gap 3** 敏感目录代理性能 | 🟡 设计未细化 | 🟡 Phase B-2 实施时 evaluate(单实例 FastAPI uvicorn 并发够用)|
| **Gap 4** MS-FB-006/007/008 重审 | 🔴 必须改 | ✅ MS-FB-006/007 已 merged(PR #37 / #39)+ #36 IM 推送 in-flight |
| **Gap 5** 业务权限模型 | 🔴 未规划 | ✅ OpenFGA ReBAC(verified PoC) |
| Gap 6 桌面/移动 | 🟡 §7.1 verify | 🟡 等业务侧确认;桌面用 Cyberduck/rclone 兜底 |
| Gap 7 业务元数据搜索 | 🟡 P1 | 🟡 Phase B-3 用 PG FTS;Phase C 评估 Meilisearch |
| Gap 8 预览/转码 worker pool | 🟡 P0 | ✅ 选 arq + Redis(本 ADR §6) |
| Gap 9 bucket notification 可靠性 | 🟡 PoC 未跑 | ✅ Phase A.2 已实测 |
| Gap 10 Audit schema 重写 | 🟡 PR #30 待修订 | 🟡 Phase B-2 实施时基于 PR #30 修订 |
| Gap 11 Pigsty fork 长期兜底 | 🟢 协议层耦合 | 🟢 持续 |
| Gap 12 业务 UI features | 🟡 ADR-0001 范围扩 | ✅ 本 ADR §3 + §9 Phase B-3 拆解 |
| Gap 13 IM 推送通道 | 🟡 未拍板 | 🟡 等 issue #36 MS-FB-008 起草 |

→ **Phase B 关键阻塞项(Gap 1/4/5)已全部有 verified / in-flight 方案**;Phase B 可在 ADR-0005 §7 verify 通过后立即启动。

---

## 11. 不采纳的全局替代(整体路径角度)

| 路径 | 不采纳理由 |
| --- | --- |
| **Low-code 平台**(Budibase / Appsmith / NocoBase)| 飞书深度集成需重新加,实质工作量等同 + 引入 lock-in |
| **fork 现有 DAM**(ResourceSpace / Pimcore)| PHP 老栈;飞书集成等同重写 |
| **商业 SaaS / 公有云 DAM** | 数据不出公司前提排除 |

---

## 12. 风险与回退

| 风险 | 概率 | 应对 |
| --- | --- | --- |
| OpenFGA 维护 stall | 低(CNCF + Auth0) | 协议层数据(tuples)可 export,迁 SpiceDB 数据模型相似 |
| FastAPI / Python 性能瓶颈(stream 大流量)| 中 | Phase B-2 evaluate;必要时敏感代理走 Go 子 service |
| uppy v4 后续 breaking changes | 低 | 已 pin @4 major |
| Pigsty MinIO fork stall(ADR-0005 §10.5)| 中 | escape hatch 已设计(SeaweedFS 次选 + AIStor 兜底)|
| 飞书 SDK / API 改动 | 低 | feishu bridge 已封装,改动收敛 |

---

## 13. Verify 后转 accepted 的 checklist

- [ ] ADR-0005 §7 业务侧 verify 通过 + accepted(本 ADR builds on)
- [ ] 团队 review 本 ADR(权限引擎选型 + 后端栈 + 前端栈 共识)
- [ ] PG / Redis 部署形态确认(单实例 OK?)
- [ ] CI / lint / test 工具链团队同意(uv / ruff / pytest / mypy)
- [ ] Phase B-1 出口 milestone 排期

全部 ✓ → Status 改 accepted;启 Phase B-1。

---

## 14. 关联

- ADR-0005 PR #33(builds on,Phase B 启动 blocking)
- PoC openfga(本 ADR §1 verified evidence)
- PoC pigsty-minio(本 ADR §7 部署示范)
- Issue #36 MS-FB-008 IM 推送契约(本 ADR §4.1 依赖)
- 用户决策 2026-05-16:Phase B 核心 = 飞书 + MinIO 权限管理(本 ADR framing 来源)
