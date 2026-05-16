# material-storage web — Phase B-3 业务前端

Vite + React 18 + TS + AntD 5 + react-router(HashRouter)+ @tanstack/react-query + uppy v4。

## 开发

```bash
pnpm install
pnpm dev          # http://localhost:5173/ms-static/web/
                  # 自动 proxy /api → http://localhost:8200(本地 ms-api)
```

## 构建 + 部署

```bash
pnpm build        # 输出到 ../api/app/static/web/(ms-api 通过 StaticFiles mount /static 暴露)
                  # 部署:rsync ../api/app/static/web/ 到 server2 → docker cp 进 ms-api 容器
                  # 访问:https://rusheslab.taoxiplan.com/ms-static/web/(经 nginx /ms-static/ 路由)
```

## 路由

| 路径 | 页面 | 说明 |
|---|---|---|
| `#/` | ProjectsPage | 项目卡片列表(OpenFGA 过滤后可见 + public) |
| `#/projects/:id` | ProjectDetailPage | 项目内 folder 列表 + sensitive 申请入口 |
| `#/folders/:id` | FolderDetailPage | 文件列表 + uppy 上传 + 下载 |
| `#/approvals` | ApprovalsPage | 我的申请 / admin 审批 tabs |
| `#/dev-login` | DevLoginPage | dev 模式 X-User-Id 切换(localStorage) |

## 认证

- **生产**:同源 cookie session(ms_session JWT),401 → 跳 `/api/v1/auth/login` 飞书 OIDC
- **dev**:localStorage `ms_dev_user_id`,axios interceptor 加 `X-User-Id` header
  访问 `#/dev-login` 或 `?dev=1` 进切换页

## 关键文件

- `src/api/client.ts` — axios + cookie/header 注入
- `src/api/hooks.ts` — react-query hooks(每 endpoint 一个)
- `src/components/UploadDrawer.tsx` — uppy 5-endpoint multipart 包装
- `src/App.tsx` — HashRouter + AntD App provider + 路由表
