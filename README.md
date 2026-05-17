# rushes-lab

医美机构素材管理 / 飞书集成 / 配套设计文档的 **多项目 monorepo**。每个项目独立成顶层目录,构建/测试/依赖收敛在各自项目内。

## 项目目录

| 项目 | 说明 | 状态 |
| --- | --- | --- |
| [`material-storage/`](./material-storage) | 自研医美素材库(FastAPI + React + MinIO + OpenFGA + 飞书 OIDC) | **已部署 server2 dev**(`http://8.156.34.238/ms-static/web`),Phase B 实施中 |
| [`feishu-integration/`](./feishu-integration) | 飞书集成桥接层(对内 REST / 对外飞书开放平台) | PoC 连通性已就位,Phase B 实施待启动;由独立 agent 维护,详见 [`rushes-spec/feishu/`](./rushes-spec/feishu) |
| [`rushes-spec/`](./rushes-spec) | 方案细化与决策记录(ADR / 调研 / 契约 / ROADMAP / COLLABORATION) | 持续维护 |

## 如果你是 …

### dev agent(Claude Code 会话,改 material-storage 代码)
顺序读:
1. **工作区本地** 的 `CLAUDE.md`(workspace 根,不进仓库 — 与项目所有者获取)— 顶层守则、git 身份、推送策略
2. [`rushes-spec/material-storage/ROADMAP.md`](./rushes-spec/material-storage/ROADMAP.md) — 当前迭代、待办、已知坑
3. [`rushes-spec/material-storage/ops-manual.md`](./rushes-spec/material-storage/ops-manual.md) — server2 运维事实、部署、排查 cheat sheet
4. [`rushes-spec/material-storage/permissions-model-v4.md`](./rushes-spec/material-storage/permissions-model-v4.md) — OpenFGA v4(改 permission 代码前必读)
5. [`rushes-spec/material-storage/COLLABORATION.md`](./rushes-spec/material-storage/COLLABORATION.md) — 测试反馈渠道 + issue lifecycle
6. 子项目 README:[`api/`](./material-storage/api/README.md) + [`web/`](./material-storage/web/README.md)

### field tester(用产品测试 + 反馈,不写代码)
- **不需要 GitHub 账号**。通过团队的 feedback gatekeeper 反馈,任何形式(口头/微信/飞书/录屏)都可以
- 详见 [`rushes-spec/material-storage/COLLABORATION.md`](./rushes-spec/material-storage/COLLABORATION.md) §1.5 反馈路径
- 测试入口:`https://rusheslab.taoxiplan.com/ms-static/web`(dev,期望 breaking changes)
  - ⚠️ **务必走域名,不要走 IP**。OAuth 回调固定在域名,IP 入口会 state mismatch 登录失败
- 第一次登录后进 📚 **上手指南(demo)** 项目 → 01-入门文档 → 点 *操作手册.md / 权限模型.md*(👁 预览按钮)— 不写代码也能完整读懂产品(2026-05-18 起 seed 自动可见)

### feedback gatekeeper(收 tester 反馈 + 代提 GitHub issue)
- 必读 [`rushes-spec/material-storage/COLLABORATION.md`](./rushes-spec/material-storage/COLLABORATION.md) 全文
- 提 issue:`gh issue create --template {bug,feature,frontend-feature}.yml`(或在 GitHub 网页 "New issue" 选模板)

### feishu agent(改飞书集成代码)
- [`rushes-spec/feishu/COLLABORATION.md`](./rushes-spec/feishu/COLLABORATION.md) — 平级 agent 协作规则 + git mutex lock 协议
- [`rushes-spec/feishu/`](./rushes-spec/feishu) — 契约 / ADR / 调研

## 关键索引

| 想看 | 去 |
| --- | --- |
| 当前迭代 + 待办 + 已知坑 | [`rushes-spec/material-storage/ROADMAP.md`](./rushes-spec/material-storage/ROADMAP.md) |
| server2 运维事实 / 部署命令 / 排查 cheat sheet | [`rushes-spec/material-storage/ops-manual.md`](./rushes-spec/material-storage/ops-manual.md) |
| 权限模型 v4(OpenFGA ReBAC + 飞书 subject) | [`rushes-spec/material-storage/permissions-model-v4.md`](./rushes-spec/material-storage/permissions-model-v4.md) |
| 审计 schema | [`rushes-spec/material-storage/audit-schema.md`](./rushes-spec/material-storage/audit-schema.md) |
| 协作规则(tester / agent / 飞书侧) | [COLLABORATION (material-storage)](./rushes-spec/material-storage/COLLABORATION.md) + [COLLABORATION (feishu)](./rushes-spec/feishu/COLLABORATION.md) |
| 所有 ADR(决策) | [material-storage decisions](./rushes-spec/material-storage/decisions) + [feishu decisions](./rushes-spec/feishu/decisions) |
| 飞书契约(REST / 事件 schema / 错误码) | [`rushes-spec/feishu/contracts/`](./rushes-spec/feishu/contracts) |
| Issue 模板(bug/feat/ui) | [`.github/ISSUE_TEMPLATE/`](./.github/ISSUE_TEMPLATE) |

## Live 环境(dev)

| | URL | 说明 |
| --- | --- | --- |
| material-storage web(tester 入口) | `https://rusheslab.taoxiplan.com/ms-static/web` | server2 dev,共享,**期望 breaking changes**;OAuth 回调走此域名 |
| material-storage web(dev 调试) | `http://8.156.34.238/ms-static/web` | 同集群,直连 IP;⚠️ 登录会失败(回调在域名) |
| material-storage api(健康检查) | `http://8.156.34.238/api/v1/healthz` | 服务存活检查 |
| 飞书 bridge PoC | `https://rusheslab.taoxiplan.com/healthz` | [`feishu-integration/`](./feishu-integration) PoC |

## 仓库约定

- **多项目 monorepo**:每项目自己的 `package.json` / `pyproject.toml` / `Dockerfile`,**不**放仓库根
- 仓库根只放跨项目共用资产:本 `README.md`、`.gitignore`、`.github/`(issue 模板 / CI)
- **本仓库公开**;敏感配置(`.env` / 飞书 app secret / `DEFAULT_ORGANIZATION_ID` 值 / 真实顾客 / 员工数据)**严禁** push
- **工作区本地**还有 `CLAUDE.md` / `git.md` / `refs/`(原始方案 docx)**不进仓库** — 与项目所有者获取
- 不直推 `main`;改动走 feature branch + PR + squash-merge(详见 workspace-local `CLAUDE.md`)

## 仓库布局

```
rushes-lab/
├── README.md                    ← 本文件
├── .github/ISSUE_TEMPLATE/      ← bug / feature / frontend-feature 模板
│
├── material-storage/            ← 主项目实施
│   ├── api/                       FastAPI + PostgreSQL + OpenFGA + MinIO + 飞书 OIDC
│   ├── web/                       React 19 + Vite + AntD 6 + react-router 7
│   ├── poc/                       早期 PoC(大部分历史,仅 minio/ + openfga/ 仍 dev 依赖)
│   └── README.md
│
├── feishu-integration/          ← 飞书桥接(独立 agent 维护)
│   ├── app/                       FastAPI + Caddy + systemd PoC
│   ├── deploy/
│   └── README.md
│
└── rushes-spec/                 ← 方案 / 契约 / ADR / ROADMAP
    ├── material-storage/
    │   ├── ROADMAP.md             ← 当前位置
    │   ├── ops-manual.md          ← server2 运维
    │   ├── permissions-model-v4.md
    │   ├── audit-schema.md
    │   ├── COLLABORATION.md       ← tester ↔ dev
    │   ├── decisions/             ← ADR 0001-0006
    │   └── research/
    └── feishu/
        ├── COLLABORATION.md       ← feishu agent ↔ material-storage agent
        ├── contracts/             ← approval / approval-callback / identity / sso
        ├── decisions/             ← ADR 0001-0002
        └── research/
```
