# material-storage web

业务前端:**React 19 / Vite 8 / TS / AntD 6 / react-router 7 / @tanstack/react-query / uppy**。

## 开发

```bash
pnpm install
pnpm dev          # http://localhost:5173/ms-static/web/
                  # 自动 proxy /api → http://localhost:8000(本地 ms-api)
```

## 构建 + 部署

```bash
pnpm build        # 输出到 ../api/app/static/web/(ms-api 通过 StaticFiles mount)
                  # ms-api 在 /static/web 暴露;nginx rewrite /ms-static/(.*) → /static/$1
                  # server2 部署见 ../api/scripts/deploy_server2.sh

# 部署 web 到 server2 dev:
cd ..
./api/scripts/deploy_server2.sh       # rsync api + dist;web 是 bind mount,立即生效
```

## 路由(BrowserRouter `basename="/ms-static/web"`)

| 浏览器路径(完整) | 组件 | 说明 |
| --- | --- | --- |
| `/ms-static/web/projects` | ProjectsPage | 项目卡片列表(显示 admin / OpenFGA 过滤后可见 / public) |
| `/ms-static/web/projects/:id` | ProjectDetailPage | 三栏 workspace:左 FolderTree / 中 AssetTable(多选+批量删除)/ 右 AssetSummaryPanel |
| `/ms-static/web/approvals` | ApprovalsPage | 我的申请 / admin 审批 tabs |
| `/ms-static/web/s/:token` | SharePage | 分享落地 + 自动下载 |
| `/ms-static/web/dev-login` | DevLoginPage | dev 模式 X-User-Id 切换 |
| `/ms-static/web/me/permissions` | MyPermissionsPage | 我的权限 inventory(project + folder × 角色矩阵) |

## 认证

- **生产 / dev**:同源 cookie session(`ms_session` JWT),401 → 跳 `/api/v1/auth/login` 飞书 OIDC
- **本地无飞书**:localStorage `ms_dev_user_id`,axios interceptor 加 `X-User-Id` header;访问 `/ms-static/web/dev-login` 切换

## 关键文件

- `src/main.tsx` — root render + `BrowserRouter basename="/ms-static/web"`
- `src/App.tsx` — 路由表 + AntD theme provider
- `src/api/client.ts` — axios + cookie/header 注入
- `src/api/hooks.ts` — react-query hooks(每 endpoint 一个)
- `src/components/UploadDrawer.tsx` + `PersistentUploadDrawer.tsx` — uppy multipart + 浮动入口
- `src/components/TaskCenterDrawer.tsx` — 上传/下载进度可视化(浮动按钮触发)
- `src/components/MyRolesBadge.tsx` + `MyFolderPerms.tsx` — 权限展示组件

## 关联

- [`../api/`](../api) — 后端 endpoint 实现
- [`../../rushes-spec/material-storage/ROADMAP.md`](../../rushes-spec/material-storage/ROADMAP.md) — 前端待办
- [`../../rushes-spec/material-storage/COLLABORATION.md`](../../rushes-spec/material-storage/COLLABORATION.md) — UI 反馈走 `[ui]` issue 模板
