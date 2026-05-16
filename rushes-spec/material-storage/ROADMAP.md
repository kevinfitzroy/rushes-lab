# material-storage — 工作 ROADMAP / 待办

> 持续更新,作为 context compact 后的"事项备忘"。当一个 iter 完成 → 移到 Done 区。
> 最后更新:2026-05-16

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

---

## 进行中:**D 系列 — 项目/folder/成员管理 UI**

后端 endpoint 多数已有(PR #40 起就绪),前端补 UI + 少量新 backend endpoint。

### D iter2 — folder rename / move / delete(下个)

- **backend**:
  - `PATCH /api/v1/folders/{id}` — body: { name?, parent_folder_id? }
    - rename:更新 name + minio_prefix(级联子 folder 的 minio_prefix);需 can_edit
    - move:更新 parent_folder_id + minio_prefix;需 can_edit 源 + 目标
  - `DELETE /api/v1/folders/{id}` — 软删(set deleted_at?folder 表无该字段,需 migration 加)
    - 或硬删 + 级联子 folder + asset 都软删
    - 需 can_admin
- **frontend**:
  - FolderTree 节点右键菜单:重命名 / 移动到 / 删除
  - 移动 = Modal + 目标 folder 选择器(复用 Tree)
  - rename 行内编辑或 Modal
  - 删除 Popconfirm

### D iter3 — sensitive folder 邀请管理 UI

- **backend**:
  - `GET /api/v1/folders/{id}/members` — list invited / explicit_invited(用 OpenFGA `read` API 拿 tuples,反查 user_id → DB lookup name/email)
  - 调用方需 can_admin folder
- **frontend**:
  - 当 active folder 是 sensitive 且选 0 个 asset 时,右侧 SummaryPanel 模式切到 FolderInvitePanel
  - 列当前 members(永久 / 临时 + grant 倒计时)
  - "邀请" 按钮 → UserPicker → invite(永久 / 临时 duration)
  - 撤销按钮(per member)

### D iter4 — 项目成员管理

- **backend**:
  - `GET /api/v1/users?q=&limit=` — admin only,fuzzy name/email,返 id/name/email/avatar
  - `GET /api/v1/projects/{id}/members` — 类似 folder members,反查 OpenFGA project 关系
  - `POST /api/v1/projects/{id}/members` — body { user_id, role: 'admin'|'editor'|'viewer' }
  - `DELETE /api/v1/projects/{id}/members/{user_id}` — 撤销 OpenFGA tuple
  - 都需 admin
- **frontend**:
  - ProjectDetailPage 顶部加 "成员" 按钮 → Drawer 显示成员列表
  - UserPicker 组件(autocomplete search /users)
  - 邀请 modal:user 选 + role 选

### D iter5(可选)— project 编辑 / 归档

- **backend**:`PATCH /api/v1/projects/{id}` — name / description / visibility / archive
- **frontend**:ProjectDetailPage 加"设置"按钮 → modal

---

## Phase B-2 / B-3 收尾(独立于 D 系列,可并行)

### 飞书 OpenAPI 集成(真审批闭环)

当前 approval 走的是 admin 手动审批(POST /approvals/{id}/approve)。集成飞书后:
- **backend**:
  - `POST /api/v1/approvals` 同时调 `lark-oapi` 创建审批 instance,存 `feishu_instance_code`
  - 飞书审批模板 user 在飞书后台先配置好 approval_code
  - `POST /api/v1/webhooks/feishu` 接 `approval_instance.event` → 状态 == APPROVED 调内部 `_grant_for_approval`
  - 配置:`settings.feishu_approval_code` env
- **场景**:user 在 web 申请 → 飞书 IM 推审批卡片 → admin 在飞书 app 一键批 → backend webhook 收到 → 自动 grant + 通知

### 离职闭环(`contact.user.deleted_v3`)

PR #40 iter6 webhook handler 已 stub。补:
- `_handle_user_deleted` 实施:db lookup `users WHERE feishu_open_id=X` → call `permissions.revoke_user_completely(str(user.id))` → set `users.is_active=False + resigned_at=now`
- 飞书后台事件订阅勾选"员工离职"事件

### audit query / export endpoint

- **backend**:
  - `GET /api/v1/admin/audit?actor=&event_type=&from=&to=&limit=&offset=` — admin only
  - `GET /api/v1/admin/audit/export.csv` — 流式 CSV
- **frontend**:管理后台 audit 页(`/admin/audit`)— Table + filter

### IM 卡片推送(Gap 13)

- ADR-0005 §11.2 Gap 13 / issue #36
- 申请提交 / 状态变更 → bridge / 直接 lark-oapi 发卡片到飞书 IM
- 卡片含 "通过/拒绝" 按钮(callback)

### approval 自动过期 marker

- arq scheduled job(Phase B-4 worker 一起搭)
- 每 5min 扫 approvals WHERE status=approved AND duration_seconds IS NOT NULL AND decided_at + duration < now → status='expired'
- 配合前端 GrantCountdown(已有)

### 飞书 H5 jsapi-ticket

- PR #42 iter3 加了 `lib/feishu.ts` initFeishu stub
- 补:
  - `GET /api/v1/auth/feishu-jsapi-ticket?url=` — 后端用 `app_access_token` 调飞书 OpenAPI 拿 ticket,sign HMAC-SHA1
  - 前端 initFeishu config 调用,获 native 能力(分享、扫码、本地存储)

### 缩略图列表(B-4 配套)

- 视频/图片 worker 生成缩略图存 MinIO `thumbnails/<asset_id>.jpg`
- 前端 FolderDetailPage 加 grid 视图切换(列表 ↔ 缩略图网格)
- video 在线预览(签 short presigned + `<video>` tag)

---

## Phase B-4 — Worker / 旁路

> arq + ffmpeg + AI;独立 worker container(已在 docker-compose.yml stub)

### B-4 iter1 — arq 接入 + MinIO bucket notification

- arq Redis queue
- MinIO `mc event add` → POST 到 ms-api `/api/v1/webhooks/minio-event` → enqueue arq
- worker container `arq app.workers.main.WorkerSettings` 已配
- 简单 task:asset_created → audit log enrich(sidecar_task_started/succeeded)

### B-4 iter2 — 缩略图 + 视频转码

- `ffmpeg-python` + `pillow`
- 图片缩略图:1024px 长边 jpg
- 视频:首帧 + 中段帧 + 264 转码(360p / 720p)
- 输出到 `thumbnails/` prefix
- assets.tags JSONB 加 thumbnail_keys

### B-4 iter3 — dataset B + AI 标签

- worker 调云端 AI(qwen-vl / openai vision)出 tags
- 写 `assets.tags`:`{ai: {labels: [...], confidence: [...]}}`
- 前端 search by tag

### B-4 iter4 — 阿里云 OSS 灾备 replication

- MinIO `mc mirror` 或 lifecycle → OSS bucket
- 配 lifecycle: deleted_at > 30d 移到 OSS cold archive
- 异地灾备元数据复制

---

## 已修复但未 commit 的注意事项 / 已知坑

- `docker-compose.yml` 现已 mount `./app:/app/app:ro`(PR #47),改 .py 直接生效
- nginx config 改动需要 in-place 写(`cat > file`),不能 `mv`(会换 inode → bind mount stale)
- 新 deploy ms-api 需 `--force-recreate` 才重读 .env(`docker restart` 不重 inject env_file)
- 飞书新 user 在 OIDC 登录时自动绑 default org(`settings.default_organization_id`)
- web build:`pnpm build` → 自动输出到 `../api/app/static/web/`,rsync 到 server2 该路径即可,bind mount 立刻生效

## 关键 server / 配置(本地 server.md 已记)

- server2 8.156.34.238 PoC — docker compose stack(ms-api / ms-db / ms-redis / poc-pigsty-minio / poc-openfga / poc-nginx 等)
- server1 47.109.30.236 — Caddy + 域名 `rusheslab.taoxiplan.com` → 反代 server2:80
- 飞书 app:`cli_aa8dbee01fb99bb3`,redirect_uri `https://rusheslab.taoxiplan.com/api/v1/auth/callback`,事件 webhook `/api/v1/webhooks/feishu`
- default org id:`00000000-0000-0000-0000-0000000000a1`

## 推荐顺序

1. 完成 D iter2-4(剩余 admin UI;纯 backend + frontend,无外部依赖)
2. 选 Phase B-4 iter1+2(缩略图)— 视觉体验跃迁
3. 飞书 OpenAPI 集成(真审批闭环)— 让产品自洽业务
4. audit query 后台 / 离职闭环 — 合规底
5. AI 标签 / OSS 灾备 — 长期差异化
