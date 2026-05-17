# material-storage — 工作 ROADMAP / 待办

> 持续更新,作为 context compact 后的"事项备忘"。当一个 iter 完成 → 移到 Done 区。
> 最后更新:2026-05-17
>
> 相关文档:
> - [`permissions-model-v4.md`](./permissions-model-v4.md) — 权限模型详细
> - [`ops-manual.md`](./ops-manual.md) — **运维手册**(系统 admin / 部署 / 排查 / 灾后恢复)

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

---

## 待办

### 飞书 OpenAPI 真审批闭环 — **等用户先在飞书后台配审批模板**

IM 卡片已就绪 + approval_service.decide 抽好;只缺接飞书"工作台 → 审批"应用,让 admin 可在飞书审批后台同步处理(企业既有 SOP)。
- **前置依赖**:飞书后台先配审批模板,把 approval_code 填 .env `FEISHU_APPROVAL_CODE`
- **backend**:
  - `POST /api/v1/approvals` 同时调 `lark-oapi` 创建审批 instance,存 `feishu_instance_code`
  - `POST /api/v1/webhooks/feishu` `approval_instance` 分支:status==APPROVED 调内部 `approval_service.decide(approve)`
- **场景**:user web 申请 → 同时 IM 卡 + 飞书审批工单 → admin 任一渠道一键批 → backend 落库 + 通知

### B-4 视频缩略图 + 转码(下个 B-4 iter)

- `ffmpeg-python`:ffprobe 拿 duration + 首帧/中段帧 → thumbnails/{aid}.jpg
- 可选:264 转码 360p/720p 供低带宽预览
- AssetThumbnail 自动 fallback(video → 视频 placeholder + 之后填真缩略图)
- 风险:流式拉大视频 + ffmpeg 内存 / 临时盘;先 50MB-cap pilot

### B-4 iter3 — AI 标签

- worker 调云端 AI(qwen-vl / openai vision)给图片打 tag
- 写 `assets.tags.ai = {labels: [...], confidence: [...]}`
- 前端 search by tag(列表过滤 + 标签云)

### B-4 iter4 — 阿里云 OSS 灾备

- MinIO `mc mirror` 或 lifecycle → OSS bucket
- 配 lifecycle: deleted_at > 30d 移到 OSS cold archive
- 异地灾备元数据复制

### approval 自动过期 marker

- arq scheduled job(B-4 worker 配套)
- 每 5min 扫 `approvals WHERE status=approved AND duration_seconds IS NOT NULL AND decided_at + duration < now → status='expired'`
- 配合前端 GrantCountdown(已有)

### IM 卡片 update(approve 后改卡片状态)

- 现在卡片回调 toast OK,但原卡片不更新("待审"标 → "已通过 by Evan")
- 需要 approvals 表加 `feishu_card_message_ids JSONB`(存 admin open_id → message_id 映射)
- approve/reject 后用 `feishu.update_im_card(message_id, build_approval_decided_card())`

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

---

## 已知坑 / 部署 cheat sheet

- `docker-compose.yml` 现已 mount `./app:/app/app:ro` ms-api + ms-worker 都 bind(改 .py 直接生效)
- nginx config 改动需要 in-place 写(`cat > file`)不能 `mv`(换 inode → bind mount stale)
- 新 deploy ms-api 需 `--force-recreate` 才重读 .env;`docker restart` 不重 inject env_file
- force-recreate 后 docker exec pip install 的 dev 依赖(pytest 等)会丢,需重装
- 飞书新 user OIDC 登录自动绑 default org(`settings.default_organization_id`)
- web build:`pnpm build` → `../api/app/static/web/`,rsync server2 该路径,bind mount 立刻生效
- 飞书卡片 button url 必须包成 applink(`feishu_cards.applink_open`)才在飞书内 webview 打开(PR #49 修);multi_url.pc_url 也要走 applink
- audit.write 内部已自带 commit(PR #49 修);调用方不需要再 commit audit 行
- OpenFGA subject 全用飞书 ID:`user:<open_id>` / `department:<dept_id>` / `group:<gid>` / `organization:<tenant_key>`(PR #51 起;不再用 internal UUID)
- 缩略图走 short presigned **不走 OpenFGA enforce**(PR #57 决策:1024px 模糊化,信息密度低)
- pyproject.toml 改 `asyncio_default_*_loop_scope=session`(PR #51 修 asyncpg cross-loop bug);ms-api 容器 force-recreate 后需 `docker cp pyproject.toml` 一次

## 关键 server / 配置(本地 `server.md` 已记)

- server2 8.156.34.238 PoC — docker compose stack(ms-api / ms-worker / ms-db / ms-redis / poc-pigsty-minio / poc-openfga / poc-nginx)
- server1 47.109.30.236 — Caddy + 域名 `rusheslab.taoxiplan.com` → 反代 server2:80
- 飞书 app:`cli_aa8dbee01fb99bb3`,redirect_uri `https://rusheslab.taoxiplan.com/api/v1/auth/callback`,事件 webhook `/api/v1/webhooks/feishu`(含 contact 4 events + card.action.trigger + approval_instance)
- default org id:`00000000-0000-0000-0000-0000000000a1`(tenant_key `dev_tenant_001`)
- OpenFGA store:`01KRRR86H5HDM0KP0ZKBZC19TN`(model v4)

## 推荐顺序

1. **飞书审批模板配置**(用户操作)→ 飞书 OpenAPI 真审批闭环 — 最高 ROI 完成企业 SOP 自洽
2. B-4 iter2 视频缩略图(ffmpeg 接入)— 视觉体验跃迁(图片已有)
3. IM 卡片 update(approve 后改卡片)— 完善卡片交互闭环
4. approval 自动过期 + AI 标签 + OSS 灾备 — 长期差异化
