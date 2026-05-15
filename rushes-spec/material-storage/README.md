# material-storage 方案细化

针对内部「素材存储与管理系统」(对应仓库根的 `material-storage/` 实施目录)的设计工作区。

## 已知约束(用户口述,逐步沉淀)

- 数据规模:**约 100 TB**(5 年内),以**短视频成片 + 拍摄原片**为主,单文件 < 1 GB
- 工作流:**不在存储上挂载剪辑**(下载-剪-回传 或 Web 浏览)
- 用户规模:百人级(粗估)
- 部署形态:以**内网**为主,需支持异地访问
- IM/审批通道:**飞书 / Lark**(2026-05-15 由企业微信切换过来,理由:对第三方开发者对接更友好)
- 调研产物语言:zh-CN;技术术语保留英文原词

> 旧方案 v2 docx 留在工作区本地 `refs/` 下,不进仓库。仅当某条决策在 docx 里有明确依据时,在 ADR 里以"既有方案 v2 倾向 X,理由 Y"的形式抽象引用。

## 开放问题(滚动维护)

| # | 问题 | 状态 | 关联调研 / ADR |
| --- | --- | --- | --- |
| Q1 | **文件管理系统选型**:用什么承载视频素材的存储/检索/分享/权限 | v0.2 已落,候选重扫至 NC / Seafile / oCIS(Q1 PoC 阶段二次验证 oCIS PosixFS 与 Seafile 旁路接入) | [`research/file-management-system.md`](./research/file-management-system.md) |
| Q2 | ~~用户身份源~~ | ✅ **已收敛:飞书通讯录作 SoT**(2026-05-15) | [ADR-0002](./decisions/0002-feishu-contacts-as-identity-source.md) + [feishu 侧调研](../feishu/research/contacts-as-identity-source.md) |
| Q3 | **飞书审批对接** | 已 handoff 给 `feishu-integration`,ADR + contract v1 + PoC 均已合并 main | [`../feishu/`](../feishu/) |
| Q4 | 后端技术栈是否锁定 Python (FastAPI + Celery) | 暂列,优先级低 | — |

**依赖关系(已重整):** Q2 / Q3 已先于 Q1 收敛(通过飞书 SoT + bridge 抽象,Q1 选型对 Q2/Q3 影响小,见 ADR-0002 §"影响 - Bridge 角色范围")。Q1 仍是 PoC 优先项,但不再阻塞 Q2/Q3 推进。

## 决策(ADR)

| # | 标题 | 状态 |
| --- | --- | --- |
| [0001](./decisions/0001-no-full-custom-web-ui.md) | 不走"全自研 FastAPI Web UI"作为文件管理主体 | accepted |
| [0002](./decisions/0002-feishu-contacts-as-identity-source.md) | 采用飞书通讯录作 material-storage 身份源 (SoT) | accepted |
| 0003(预期) | 文件管理底座选型(等 Q1 PoC 决议) | 待写 |
