# material-storage 方案区

针对内部「医美素材库」(对应仓库根的 [`material-storage/`](../../material-storage) 实施目录)的设计 / 调研 / 决策 / 协作工作区。

## 当前状态

**Phase B 主体已实施 + 部署 server2 dev**(`http://8.156.34.238/ms-static/web`)。迭代里程碑、待办、已知坑详见 [`ROADMAP.md`](./ROADMAP.md)。

## 文档索引

### 持续维护(改代码前必看)

| | 用途 |
| --- | --- |
| [`ROADMAP.md`](./ROADMAP.md) | 当前迭代里程碑、待办、已知坑、部署 cheat sheet |
| [`ops-manual.md`](./ops-manual.md) | server2 运维事实 / 部署命令 / 飞书通讯录同步 / 排查 cheat sheet |
| [`permissions-model-v4.md`](./permissions-model-v4.md) | OpenFGA ReBAC v4 权限模型(改 permission 代码前必读) |
| [`audit-schema.md`](./audit-schema.md) | 审计落库 schema |
| [`COLLABORATION.md`](./COLLABORATION.md) | tester 反馈 ↔ dev 协作契约(field tester / gatekeeper / dev 三角)+ issue lifecycle |

### 决策记录(ADR — 按编号读)

| # | 标题 | 状态 |
| --- | --- | --- |
| [0001](./decisions/0001-no-full-custom-web-ui.md) | 不走"全自研 FastAPI Web UI"作为文件管理主体 | accepted(后被 0005 部分翻转 — 改走自研 + MinIO,不走第三方文件管理器) |
| [0002](./decisions/0002-feishu-contacts-as-identity-source.md) | 飞书通讯录作 SoT(身份源) | accepted |
| [0003](./decisions/0003-seafile-only-poc.md) | v0.5 Seafile-only PoC | **superseded by 0005** |
| [0005](./decisions/0005-drop-seafile-middle-layer-minio-only.md) | 抛弃 Seafile 中间层,自研 + MinIO-only | accepted ⭐ |
| [0006](./decisions/0006-phase-b-tech-stack.md) | Phase B 技术栈选型(Python 3.12 / FastAPI / OpenFGA / MinIO / 飞书 OIDC) | accepted |

> ADR 编号 0004 空位(未起草)。

### 调研笔记

[`research/`](./research) — 不强制顺序;按 ROADMAP / ADR 中的引用按需查阅。

## 历史背景(已收敛的开放问题)

| # | 问题 | 当前状态 |
| --- | --- | --- |
| Q1 | 文件管理底座选型 | ✅ **自研 + MinIO**([ADR-0005](./decisions/0005-drop-seafile-middle-layer-minio-only.md));早期候选 Seafile/NC/oCIS 对比见 [`research/file-management-system.md`](./research/file-management-system.md) |
| Q2 | 用户身份源 | ✅ **飞书通讯录作 SoT**([ADR-0002](./decisions/0002-feishu-contacts-as-identity-source.md) + [feishu 侧调研](../feishu/research/contacts-as-identity-source.md)) |
| Q3 | 飞书审批对接 | ✅ Handoff 给 [`../feishu/`](../feishu);契约 v1+ 已 merge |
| Q4 | 后端技术栈 | ✅ Python 3.12 / FastAPI([ADR-0006](./decisions/0006-phase-b-tech-stack.md)) |

## 仓库公开,注意脱敏

- 真实顾客资料(术前/中/后照、姓名、手机)**严禁** 进 spec / issue / commit(参 [COLLABORATION §4.3](./COLLABORATION.md))
- 飞书 app secret / `DEFAULT_ORGANIZATION_ID` 真值 / 客户数据 / 财务数 — 不进
- 通用化的设计依据 OK(配额、并发数、技术名词)
