# material-storage — 工作 ROADMAP / 待办

> 持续更新,作为 context compact 后的"事项备忘"。当一个 iter 完成 → 移到 Done 区。
> 最后更新:2026-05-18(回写 #82-#103 + 整理 dogfood retro 留存 / B-4 iter2 视频缩略图已 ship)
>
> 相关文档:
> - [`permissions-model-v4.md`](./permissions-model-v4.md) — 权限模型详细
> - [`ops-manual.md`](./ops-manual.md) — **运维手册**(系统 admin / 部署 / 排查 / 灾后恢复)
> - [`COLLABORATION.md`](./COLLABORATION.md) — tester / gatekeeper / dev 协作契约(2026-05-17 起)

## Phase B 完成里程碑

| PR | commit | 内容 |
|---|---|---|
| #33 | 95019a0 | ADR-0005 accepted + ADR-0006 + PoC openfga + Phase B-1 skeleton |
| #40 | 38ee5a4 | Phase B-2 — DB schema + OpenFGA + presign + audit + routers + uppy 前端 + 500MB 大文件 e2e 实测 pass |
| #42 | 1a3eb7f | Phase B-3 iter1-3 — Vite+React+AntD 业务前端 + 飞书 OIDC 实跑通 + UI polish + BrowserRouter + code split + mobile |
| #44 | 7392a06 | 后台上传 — uppy 全局 store + 浮动进度按钮 |
| #45 | 3dc2d47 | 统一任务中心(上传 + 下载进度可视化)+ multipart 修复 |
| #46 | 7d57371 | 三栏 workspace 布局 + 多选 + 批量删除 + 深层文件夹 seed(101 folders) |
| #47 | 88a4117 | D iter1 — 新建项目 / 新建文件夹 UI;org_id auto-fill;ErrorBoundary;app/ bind mount |
| #49 | fcfe951 | 飞书 IM 卡片三件套 — 权限审批 / 资源分享(短链)/ 邀请;applink button(全平台飞书内 webview);audit commit systemic fix |
| #51 | eb929cb | **权限模型 v4** — 飞书 ID 直作 OpenFGA subject;三轴 viewer/downloader/uploader 并列;folder explicit grant 子级可超父级;sensitive 限一级;46 pytest + ADR 文档 |
| #52 | cc82a30 | **UI 现代化 P0+P1** — Curated Archive 风格:Fraunces 衬线 + 焦糖橙 accent + 暖白 canvas + AppHeader(品牌印记 + ⌘K 命令栏)+ ProjectsPage 卡片 + 三栏 polish + ApprovalsPage timeline + ShareLandingPage hero |
| #54 | 1fcafa8 | **飞书通讯录同步** — `services/feishu_contact` + `contact_sync` + 4 个 webhook event handler(user created/updated/deleted + dept updated)+ 冷启动脚本 + UserPicker + ShareModal 接入 |
| #55 | 91fd7bf | **D iter3** — sensitive folder 邀请管理 UI;GET /folders/{id}/members + FolderInvitePanel(用 UserPicker + level + duration) |
| #56 | 4cfef61 | **D iter4** — 项目成员管理;CRUD /projects/{id}/members + ProjectMembersDrawer(role segmented + 多 role 聚合)|
| #57 | 2f6b216 | **B-4 缩略图** — arq worker + Pillow + thumbnails/ + complete_upload enqueue + AssetThumbnail 组件 + backfill 脚本 + ms-worker bind mount |
| #58 | 2fec361 | **审计后台** — GET /admin/audit query + filter(actor/event_type/time)+ /audit/export.csv 流式 BOM + AdminAuditPage timeline 列表(可展开 JSON details) |
| #60 | 2287ac2 | **IM 卡片 update 闭环** — approve/reject 后 update 原 admin 收到的"待审"卡为"已通过/已拒绝(by X)";approval_service.decide merge granted_tuple_ref 修复;permissions.grant_explicit_download tuple 重复时 delete+rewrite |
| #61 | 91859fb | **权限架构 polish 三件套** — 普通 folder explicit_* CRUD + FolderGrantsPanel UI(仅一级);admin enforce 严格化(require_admin = org admin OR 任意 project admin,给 /users / /admin/* 套上);approval 自动过期 marker(arq cron 每 5min) |
| #62 | 02684d9 | **系统 admin 守门** — require_system_admin(仅 organization.admin);POST /projects 必须系统 admin + 指派项目 admin(payload.admin_user_open_id 必填);scripts/grant_org_admin.py 后台命令;/me 加 is_system_admin |
| #63 | e1d1d79 | **系统 admin 见全部 + 卡片显 admin** — list_projects 系统 admin 不 filter;ProjectOut 加 admins 字段;_fill_project_admins batch 填充;ProjectCard 加 admin 头像堆叠 + 名字 |
| #64 | 0770169 | **运维手册 ops-manual.md** — 9 大块覆盖系统 admin 管理 / 部署 / 飞书同步 / 缩略图 / 审计 / 排查 / 灾后重置 / 配置 / 紧急情景;ROADMAP 加文档索引 |
| #65 | 4d0102b | **SubjectPicker** — 统一选择用户/用户组/部门;backend GET /api/v1/groups 转调飞书 list_groups + name fuzzy;前端 SubjectPicker(Tabs)替换 3 处 InviteModal(ProjectMembers / FolderInvite / FolderGrants) |
| #66 | 50e86f5 | **ROADMAP 回写 #59-#65** — 整理 Done 区 + 删完成 waitlist + 加"权限展示加强"为新待办 |
| #67 | 542eb31 | **权限展示 4 件套 + /my-permissions** — 后端 `ProjectOut.my_roles` + `FolderOut.my_can_*`(1 次 `list_objects` × 4 + 集合 lookup 替代 N×4 串行 check);项目卡 *我·角色* chip / folder header *我:权限* chip / 成员卡 *用户/群组/部门* 来源 / 总览页(临时授权 + 角色项目 + 仅访客分段);AppHeader 加导航 + ⌘K 命令项 |
| #68 | 2a61bdf | **deploy 脚本现代化** — `scripts/deploy_server2.sh` 默认 ssh key auth(SSH_PASS 兜底);修 `USER` 与 shell `$USER` 冲突的 rsync Permission denied;.env heredoc 补 `WEB_APP_BASE_URL`(Settings 必填) |
| #70 | fbce2a8 | **ROADMAP 回写 #66-#68** — Done 表加 3 条;待办里删"权限展示加强"(已落地)+ 新增 dev_bootstrap v3→v4 stale(issue #69) |
| #71 | 30cc078 | **deploy 不再 clobber server2 .env** — 默认保留远端 .env(避免 heredoc 老 PoC 飞书 app 覆盖手工调过的 `cli_aa8dbee01fb99bb3` 凭据导致 OAuth 20029);`INIT_ENV=1` 才会重写;heredoc 凭据加注释 |
| #72 | 3a3587e | **ROADMAP 回写 #70-#71** — 加 .env clobber 坑提醒 |
| #73 | 15355e7 | **SPA 刷新无尾斜杠 URL 跳错误页修复** — `app/main.py` 加 `@app.get("/static/web")` 直接返 index.html(绕开 StaticFiles 的目录 307 → 内部路径 + http 降级);Dockerfile uvicorn 加 `--proxy-headers --forwarded-allow-ips '*'` 防御性兜底其他 redirect |
| #74 | ff2e99d | **ROADMAP 回写 #72-#73** — 加 DEFAULT_ORGANIZATION_ID 必填 + 307 必须指 public 路径两条坑 |
| #75 | 47034a9 | **UserMenu open_id 完整显示 + 复制** — 之前只显前 16 位 + 省略号,改成 ellipsis 撑满 + 末尾 Copy icon(navigator.clipboard + Check 反馈 + toast);maxWidth 360 防超长撑爆;stopPropagation 防点 copy 关闭 dropdown |
| #76 | e12f55e | **ROADMAP 回写 #74-#75** |
| #77 | 62aff65 | **系统 admin 全权限直通** — 之前 assets.py(5 处)/ share.py(2 处)仍走纯 OpenFGA check,系统 admin 没显式 grant 时下载/上传/分享会 403。新增 `Depends(get_is_system_admin)` → bool 抽 default-org → is_org_admin 逻辑;projects/folders 三处内联替换 + assets/share 7 处加直通 `is_system_admin or check(...)`;audit 不变(系统 admin 行为照记) |
| #78 | d2cc7d4 | **项目卡空 admin 显示"未指派" + ops 强调多 admin** — 之前 admins 为空时静默隐藏整段 Admin chip;改成 label 始终显示,空时渲染斜体"未指派"+ tooltip 指引指派路径。ops-manual §1 加"关键事实"块:数量无硬上限(重复跑 `grant_org_admin` 加多个)+ 系统 admin 所有 endpoint 全权限(PR #77 后端覆盖)+ audit 照记 |
| #79 | e41ccb1 | **ROADMAP 回写 #76-#78** |
| #80 | e0238b7 | **folders/project-members 系统 admin 直通补全 + 医美短视频 seed 脚本** — PR #77 漏修 8 处 folders.py(create/list/invite/members/grants)+ projects.py `_enforce_project_admin` 没传 `is_system_admin`,导致系统 admin 实测无法创建文件夹;list_folders 的 sensitive 段也加直通(用 SQL 全拿 不走 OpenFGA list_objects)。新增 `scripts/seed_admin_projects.py` 为每个 active user 创建 `<name> · 个人素材库` + 11 文件夹结构(01 客户原片 sensitive / 02 工作素材 + 3 子 / 03 成片 + 3 子 / 04 平面 / 05 BGM);已 apply 10 user × 110 folders |
| #82 | 35a1dc0 | **tester ↔ dev 协作契约 + issue templates** — `rushes-spec/material-storage/COLLABORATION.md`(反馈渠道 + lifecycle + 严重度分级 + 敏感数据红线)+ 4 个 `.github/ISSUE_TEMPLATE/*.yml`(bug / feature / frontend-feature / config)+ auto-label |
| #83 | 55fcc7b | **COLLABORATION 加 gatekeeper 角色** — field tester(不需 GitHub)/ feedback gatekeeper(GitHub-savvy 1 人代提 issue)/ dev 三角;§0 fallback 全员无账号时 dev 兼 gatekeeper |
| #84 | ccc9584 | **刷新 9 个 README** — 顶层 README + api/web/poc/spec 各级,反映 Phase B 已部署 + 修事实错误(React 18→19, HashRouter→BrowserRouter, AntD 5→6);加 dev/tester/gatekeeper/feishu agent 角色入口 + Live 环境表 |
| #90 | f45f5c3 | **tester 入口 + logout redirect 用域名,避开 MinIO Console fallback**(closes #85 #86)— README field tester 入口改 https 域名(IP 入口 OAuth state mismatch);`_DEFAULT_AFTER_LOGIN` / UserMenu 都显式 `next=/ms-static/web/`,nginx `/` 默认上游是 MinIO Console |
| #92 | 3ebaa68 | **sensitive folder 创建者自动 invited_downloader + 同名冲突 409 替代 stacktrace**(closes #87)— sensitive_folder model `can_view` 不含 admin,创建者若无显式 invite 看不到自建 folder(死循环);bootstrap_sensitive_folder 后立即 `invite_to_sensitive_folder(creator, downloader, permanent)`;`uq_folder_project_prefix` 命中改 409 友好文案,不再 leak asyncpg |
| #93 | 3210829 | **GroupPicker empty 文案改'无匹配项'**(closes #89)— 原 `notFoundContent` 把"搜不到"和"未开 contact:group:readonly"合并易误导;配合用户去飞书后台开通 scope(已开通 2026-05-17) |
| #94 | 5521407 | **AssetThumbnail 去掉 `loading="lazy"`**(closes #88)— AntD Table cell viewport check 在 SPA 路由 transition 时误判,首次进入 folder 缩略图不显示需 F5;假设是浏览器原生 lazy 时序问题,去掉一行验证 |
| #95 | 95ef2f1 | **deploy_server2.sh hygiene** — step 6/7/8 用 `set -o pipefail` + `if ssh_run ...; then ok; else warn fi`(远端 bash 默认无 pipefail,`docker ... | tail` 让失败被 tail 吞 exit code → 之前永远显示假 ✓);新加 step 3.5 部署前备份 ms-api logs 到 `/tmp/ms-api-{ts}.log`(`--build` recreate 会丢) |
| #96 | 241ea7d | **A bucket retro tightening** — 4 处 stacktrace leak 同 #87 模式(deps.py / projects.py / webhooks.py)友好文案 + log 内部;CORS `allow_origins=["*"]` 改 explicit list(env-driven,默认从 `web_app_base_url` derive 同源);`admin.py` 4 endpoint `require_admin` → `require_system_admin`(over-permissive 收紧);`approvals.py` approve/reject 加 `is_system_admin` bypass(跨 router 一致) |
| #97 | 40ea983 | **demo-onboarding public 项目 seed** — `scripts/seed_onboarding_project.py` + `scripts/seed_assets/*.md` 3 个文档;创建 visibility=public 项目 + 3 root folder(`01-入门文档` 操作手册.md / 权限模型.md;`02-示例素材` PIL 生成 3 张 PNG;`03-敏感示例` sensitive folder + 敏感文件夹示例说明.md + 占位图);alice 自动 invited_downloader;deploy step 6.5 自动跑(idempotent uuid5) |
| #98 | fe9dc08 | **AssetPreviewModal md/txt** — 新组件 react-markdown + remark-gfm;AssetSummaryPanel 在可预览文件上加"预览"按钮(👁,条件 render);弹全屏 modal 内 fetch presigned URL → text content 渲染;vendor +38KB |
| #99 | 17db0a4 | **AssetPreviewModal 加 image kind** — png/jpg/jpeg/gif/webp/svg/bmp/avif/ico;不 fetch body,直接 `<img src={presigned}>`;max-height 65vh 自适应 |
| #100 | a409af2 | **AssetPreviewModal 加 pdf kind** — `<iframe src={presigned}>` 浏览器原生 viewer,零库依赖,height 68vh |
| #102 | e799921 | **B-4 iter2 视频缩略图 worker**(#101 vertical slice)— 替换 `transcode_proxy` stub 为 `generate_video_thumbnail`;Range bytes=0-10485760 拉头部 + ffmpeg `-ss 1 -frames:v 1 -vf scale=1024:-2` 抽帧 + 上传 thumbnails/{aid}.jpg + 写 `asset.tags.thumbnail_key`(跟图片完全一致);complete_upload `video/*` 分支 enqueue;50MB cap + subprocess timeout 30s + fail-soft `tags.thumbnail_failed`;ffmpeg 已在 Dockerfile |
| #103 | a9756d5 | **deploy_server2.sh step 4 加 ms-worker** — 漏掉 ms-worker 让改 worker 代码 deploy 后 worker 仍跑旧 process,需手动 restart;PR #102 deploy 时发现,本 PR 修 |

---

## 待办

### 飞书 OpenAPI 真审批闭环 — **等用户先在飞书后台配审批模板**

IM 卡片已就绪 + approval_service.decide 抽好;只缺接飞书"工作台 → 审批"应用,让 admin 可在飞书审批后台同步处理(企业既有 SOP)。
- **前置依赖**:飞书后台先配审批模板,把 approval_code 填 .env `FEISHU_APPROVAL_CODE`
- **backend**:
  - `POST /api/v1/approvals` 同时调 `lark-oapi` 创建审批 instance,存 `feishu_instance_code`
  - `POST /api/v1/webhooks/feishu` `approval_instance` 分支:status==APPROVED 调内部 `approval_service.decide(approve)`
- **场景**:user web 申请 → 同时 IM 卡 + 飞书审批工单 → admin 任一渠道一键批 → backend 落库 + 通知

### B-4 iter2 收尾 — 视频缩略图 backfill + 真测试(issue #101 / #104)

vertical slice 已 ship(PR #102 + #103 deploy 修)。剩:
- `scripts/backfill_video_thumbnails.py` 对历史已上传 video asset 补缩略图(类比 `backfill_thumbnails.py`)
- 真 mp4 e2e 测试 — issue #104 给 gatekeeper 的 7-case 矩阵(小/中/大/mov/短/h265/损坏);跑过 + 评论后 close #101 #104
- 现在 demo-onboarding 没视频不阻塞,等 gatekeeper 上传几个 mp4 后再 backfill

### B-4 iter3 — AI 标签

- worker 调云端 AI(qwen-vl / openai vision)给图片打 tag
- 写 `assets.tags.ai = {labels: [...], confidence: [...]}`
- 前端 search by tag(列表过滤 + 标签云)

### B-4 iter4 — 阿里云 OSS 灾备

- MinIO `mc mirror` 或 lifecycle → OSS bucket
- 配 lifecycle: deleted_at > 30d 移到 OSS cold archive
- 异地灾备元数据复制

### 飞书 H5 jsapi-ticket

- 当前 `lib/feishu.ts` 是 stub
- 后端 `GET /api/v1/auth/feishu-jsapi-ticket?url=` 用 `app_access_token` 拿 ticket + HMAC-SHA1 签
- 前端 initFeishu config 获 native 能力(分享 / 扫码 / 本地存储)

### D iter5(低优先级)— 项目编辑 / 归档

- `PATCH /api/v1/projects/{id}` — name / description / visibility / archive
- ProjectDetailPage 加"设置"按钮 → modal
- 没具体需求场景驱动,先不做

### D iter2(低优先级)— folder rename / move / delete

- 产品上"开一级 folder 来解决"已覆盖大部分需求;若实际用了发现痛再做
- `PATCH /api/v1/folders/{id}` rename / move + DELETE 软删

### dev_bootstrap v3→v4 stale(issue #69,P2)

- `scripts/dev_bootstrap.py` 仍调 `assign_user_to_organization`(已重命名 `add_user_to_organization`)+ 写 v3 才有的 `editor` project 关系
- 不挂线上业务,但 dev 数据 reset 后 alice org admin tuple 没建,deploy step 6 一直 ⚠(PR #95 把假 ✓ 修成真 ⚠ 后噪音可控)
- e2e step 7 `S2 project not in list` 红色 ✗ 也是它 cascading
- `seed_onboarding_project.py`(PR #97)已经做了 minimal alice upsert + project admin tuple,所以 demo-onboarding 不依赖 dev_bootstrap
- 下次需要 reset 数据时一并修;顺手也查 `scripts/seed_demo_data.py` 同类腐烂

### B bucket — 测试厚度(retro #91,P2)

dogfood retro 发现 api test 极薄(3 file:schema/healthz/v4_perms),web 0 个 unit test。5 个 tester bug(#85-#89)全靠 manual 抓。dogfood 阶段还在迭代不急,但 prod 化前必须涨:
- folders/assets/share/approvals router 各加一组 integration test
- UserPicker/GroupPicker/FolderTree/AssetTable 等核心组件加 vitest

### Asset preview 二期 — docx / xlsx / video / heic(候选,等需求驱动)

- markdown / text / image / pdf 已 ship(PR #98/#99/#100)
- docx:mammoth (~400KB,lazy-load)
- xlsx:sheetjs (~700KB,lazy-load)
- video:`<video controls src={presigned}>` 简单但需控件 UX polish — 独立 issue 时再 frame
- HEIC(iOS 默认):浏览器原生不支持,heic-to (~200KB) 兜底

### gatekeeper triage 权限(ops,pending)

- @Strelizialeomon 当前是 Read collaborator,加 label / close issue 都 403
- 2026-05-18 尝试 API PUT permission=triage 返 422 RepositoryInvitation 错(可能 GitHub UI 操作更稳)
- 走 GitHub Settings → Collaborators 手动升级最稳

### 已放弃 / 不做

- **挂载盘**(WebDAV / S3 client mount via STS)— 2026-05-18 讨论后放弃;sensitive folder + 临时授权语义难映射 IAM,加上绕开 audit;有需求再开 issue 重提

---

## 已知坑 / 部署 cheat sheet

- `docker-compose.yml` 现已 mount `./app:/app/app:ro` ms-api + ms-worker 都 bind(改 .py 直接生效)
- nginx config 改动需要 in-place 写(`cat > file`)不能 `mv`(换 inode → bind mount stale)
- 新 deploy ms-api 需 `--force-recreate` 才重读 .env;`docker restart` 不重 inject env_file
- **PR #103 起 `deploy_server2.sh` step 4 含 ms-worker** — 改 worker 代码后 deploy 自动 reload(之前要手动 `docker compose restart ms-worker`)
- **PR #95 起 deploy step 3.5 自动备份上轮 ms-api logs 到 `/tmp/ms-api-{ts}.log`**(`--build` recreate 会丢);forensic 排查走 `ssh root@8.156.34.238 'ls -lt /tmp/ms-api-*.log | head -5; tail -200 <ts file>'`
- **PR #95 起 deploy step 6/7/8 是 ⚠ 不是假 ✓** — 远端 bash 默认无 pipefail,以前 `docker ... | tail` 让失败被吞;现在 set -o pipefail 真退 exit code,失败 warn 不阻塞(#69 bootstrap stale / e2e cascading / large file upload 当前都 ⚠ 不是真崩)
- **PR #97 起 deploy step 6.5 自动 seed demo-onboarding public 项目** — 操作手册.md / 权限模型.md / 敏感文件夹示例说明.md + PIL 生成示例 PNG;db 清空重建后用户立刻有上手内容
- force-recreate 后 docker exec pip install 的 dev 依赖(pytest 等)会丢,需重装
- 飞书新 user OIDC 登录自动绑 default org(`settings.default_organization_id`)
- web build:`pnpm build` → `../api/app/static/web/`,rsync server2 该路径,bind mount 立刻生效
- 飞书卡片 button url 必须包成 applink(`feishu_cards.applink_open`)才在飞书内 webview 打开(PR #49 修);multi_url.pc_url 也要走 applink
- audit.write 内部已自带 commit(PR #49 修);调用方不需要再 commit audit 行
- OpenFGA subject 全用飞书 ID:`user:<open_id>` / `department:<dept_id>` / `group:<gid>` / `organization:<tenant_key>`(PR #51 起;不再用 internal UUID)
- 缩略图走 short presigned **不走 OpenFGA enforce**(PR #57 决策:1024px 模糊化,信息密度低);**视频缩略图 PR #102 起沿用同 path**,前端 AssetThumbnail 零改动
- **sensitive folder model `can_view` 不含 admin** — admin from parent project 不隐式 can_view;PR #92 起 create 时自动给 creator `invited_downloader`(否则"建了看不见"死循环);邀请别人仍走正常 invite 路径
- **PR #96 起 admin.py 4 endpoint 用 require_system_admin** 不是 require_admin — 任意 project admin 不能再访问 /admin/audit / /admin/feishu/test-card 等;接到"管理后台 403"反馈不是 bug 是收紧
- **PR #96 起 CORS allow_origins 不是 `*`** — env `CORS_ALLOW_ORIGINS=` 留空时自动从 `web_app_base_url` derive 同源 origin;同源主路径零配置,cross-origin 显式 list
- **AssetPreviewModal(PR #98-#100)cover md/txt/image/pdf** — 选中 asset 时右栏多 👁 预览按钮,弹全屏 modal;`isPreviewable(a)` 决定按钮是否显示
- pyproject.toml 改 `asyncio_default_*_loop_scope=session`(PR #51 修 asyncpg cross-loop bug);ms-api 容器 force-recreate 后需 `docker cp pyproject.toml` 一次
- server2 `.env` 是**手工调过的真值**(尤其飞书新 app `cli_aa8dbee01fb99bb3`,deploy 脚本 heredoc 写的是老 PoC app — 仅示例);`deploy_server2.sh` 默认保留远端 .env 不动,只有 `INIT_ENV=1` 才会重写(PR #71 起);新机器 bootstrap 后必须人工把 `server.md` 里的"新的 feishu app"凭据 sed 进 .env + `force-recreate ms-api`
- server2 `.env` 必填 `DEFAULT_ORGANIZATION_ID`(新 user OIDC 登录自动绑该 org;`scripts/grant_org_admin --list` 也用它);PoC 默认 `00000000-0000-0000-0000-0000000000a1`(dev-clinic);**deploy 脚本 INIT_ENV 路径目前未写入这一行,首次 bootstrap 后需手工 append + force-recreate**
- public URL 用 `/ms-static/web/`(nginx rewrite 到内部 `/static/web/`);**任何 ms-api 返 307 redirect 必须显式指向 public 路径而非内部 `/static/`**,否则浏览器 URL 跳到 `/static/web/` 导致 SPA basename mismatch 崩(PR #73 起 ms-api 加 `--proxy-headers` + 单独 route 处理 `/static/web` 无尾斜杠 case)
- **飞书 OpenAPI scope 现状**:`contact:user.base:readonly` + `contact:group:readonly`(2026-05-17 开)+ `im:message` + OIDC 基础;**未开** user.email / user.department(SubjectPicker 搜结果 email 字段为空是已知,不是 bug)

## 关键 server / 配置(本地 `server.md` 已记)

- server2 8.156.34.238 PoC — docker compose stack(ms-api / ms-worker / ms-db / ms-redis / poc-pigsty-minio / poc-openfga / poc-nginx)
- server1 47.109.30.236 — Caddy + 域名 `rusheslab.taoxiplan.com` → 反代 server2:80
- 飞书 app:`cli_aa8dbee01fb99bb3`,redirect_uri `https://rusheslab.taoxiplan.com/api/v1/auth/callback`,事件 webhook `/api/v1/webhooks/feishu`(含 contact 4 events + card.action.trigger + approval_instance)
- default org id:`00000000-0000-0000-0000-0000000000a1`(tenant_key `dev_tenant_001`)
- OpenFGA store:`01KRRR86H5HDM0KP0ZKBZC19TN`(model v4)

## 推荐顺序

1. **idle 等 gatekeeper 反馈** — issue #104 视频缩略图 7-case 测试,有结果后 close #101/#104 或 follow-up 修 bug
2. **飞书审批模板配置**(用户操作)→ 飞书 OpenAPI 真审批闭环 — 最高 ROI 完成企业 SOP 自洽
3. B-4 iter3 — AI 标签(图片打 tag + search by tag)— 用户找素材的核心 UX 跃迁
4. #69 dev_bootstrap v3 真修 — 消 deploy step 6/7 ⚠ 噪音
5. B bucket 测试厚度补一组 integration test — prod 化前的硬要求
4. approval 自动过期 + AI 标签 + OSS 灾备 — 长期差异化
