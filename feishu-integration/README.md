# feishu-integration

飞书(Feishu / Lark)集成层 —— 把"调用飞书开放平台"的能力封装成稳定 REST 接口,供仓库内其他项目调用。

## 角色

这是一个**桥接服务(bridge / middleware)**:

- **对内**(upstream:`material-storage` 等仓库内项目):暴露 REST API,语义化封装"申请审批 / 解析用户 / 推送消息 / SSO 鉴权"等业务能力
- **对外**(downstream:飞书开放平台):管理 `tenant_access_token`、接收事件 webhook、按飞书 API 协议调用

## 工作区边界

- **本目录(`feishu-integration/`)的所有代码与配置由 feishu agent 维护。** material-storage agent 不应在此目录提交。
- 与其他项目的对接走**契约**:`rushes-spec/feishu/contracts/*.md`,任何契约变更必须 PR review,双方都签字。
- 工作流细节、协作规则见 [`../rushes-spec/feishu/COLLABORATION.md`](../rushes-spec/feishu/COLLABORATION.md)。

## 状态

🟡 **未开始实施。** 方案区文档已就位(`../rushes-spec/feishu/`),feishu agent 接手时按以下顺序读:

1. [`../rushes-spec/feishu/COLLABORATION.md`](../rushes-spec/feishu/COLLABORATION.md) — 协作规则
2. [`../rushes-spec/feishu/research/approval-integration.md`](../rushes-spec/feishu/research/approval-integration.md) — 既有调研结论
3. [`../rushes-spec/feishu/requirements/from-material-storage.md`](../rushes-spec/feishu/requirements/from-material-storage.md) — material-storage 提的需求清单
4. [`../rushes-spec/feishu/README.md`](../rushes-spec/feishu/README.md) — 方案区索引

接手后第一批 deliverable 应该是:

- 在 `../rushes-spec/feishu/decisions/` 写 ADR-0001(确认走原生审批 v4)
- 在 `../rushes-spec/feishu/contracts/` 起草第一份契约(对应 material-storage 的 MS-FB-001 审批请求接口)
- 等契约 merged 后再开始 `feishu-integration/` 内的实施

## 技术栈(预定,可由 feishu agent 调整)

- Python(与 material-storage 一致,便于跨项目复用类型/工具)
- FastAPI(对外提供 REST 接口)
- 官方 SDK `lark-oapi`(处理 token / 事件 / 卡片 / 加解密)
- Redis(`tenant_access_token` 中心化缓存)
- 配置外置(env / vault),敏感凭据**不入仓库**(`app_secret` / `encrypt_key` / `verification_token`)
