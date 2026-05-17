# material-storage

自研医美素材库:**FastAPI + React + MinIO + OpenFGA + 飞书 OIDC**。Phase B 实施中,已部署 server2 dev(`http://8.156.34.238/ms-static/web`)。

> 详细方案 / ADR / 当前位置 / 运维手册都在 [`../rushes-spec/material-storage/`](../rushes-spec/material-storage)。
> 协作 / 反馈规则在 [`../rushes-spec/material-storage/COLLABORATION.md`](../rushes-spec/material-storage/COLLABORATION.md)。

## 子项目

| 路径 | 说明 |
| --- | --- |
| [`api/`](./api) | Python 3.12 / FastAPI / PostgreSQL 16 / OpenFGA / MinIO / 飞书 OIDC |
| [`web/`](./web) | React 19 / Vite 8 / AntD 6 / react-router 7(BrowserRouter basename=`/ms-static/web`) |
| [`poc/`](./poc) | 早期文件管理底座 PoC(**大部分历史** — 仅 `poc/minio/` + `poc/openfga/` 仍作 dev 依赖) |

## 当前状态

Phase B 主体已实施 + 部署 server2;迭代细节、待办、已知坑见 [`../rushes-spec/material-storage/ROADMAP.md`](../rushes-spec/material-storage/ROADMAP.md)。

## 关键文档(改代码前)

| | 看 |
| --- | --- |
| 当前迭代 / 待办 / 已知坑 | [`../rushes-spec/material-storage/ROADMAP.md`](../rushes-spec/material-storage/ROADMAP.md) |
| server2 运维 / 部署 / 排查 | [`../rushes-spec/material-storage/ops-manual.md`](../rushes-spec/material-storage/ops-manual.md) |
| 权限模型 v4(OpenFGA ReBAC + 飞书 subject) | [`../rushes-spec/material-storage/permissions-model-v4.md`](../rushes-spec/material-storage/permissions-model-v4.md) |
| 审计 schema | [`../rushes-spec/material-storage/audit-schema.md`](../rushes-spec/material-storage/audit-schema.md) |
| ADR(决策) | [`../rushes-spec/material-storage/decisions/`](../rushes-spec/material-storage/decisions) |
| 测试反馈 ↔ dev 协作 | [`../rushes-spec/material-storage/COLLABORATION.md`](../rushes-spec/material-storage/COLLABORATION.md) |
