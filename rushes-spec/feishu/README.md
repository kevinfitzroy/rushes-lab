# rushes-spec / feishu

飞书(Feishu / Lark)集成的**方案区**。实施代码在 [`../../feishu-integration/`](../../feishu-integration);此目录只放方案、契约、决策、调研、需求。

## 目录索引

| 子目录 / 文件 | 用途 | 主导者 |
| --- | --- | --- |
| [`COLLABORATION.md`](./COLLABORATION.md) | **协作规则总章** —— 谁动什么、契约怎么提案、Issues 怎么用 | 双方共维护 |
| [`contracts/`](./contracts) | 接口契约(REST schema、事件 schema、错误码、版本) | feishu agent 提案,上游 review |
| [`requirements/`](./requirements) | 上游对飞书侧提的功能需求清单 | 各上游项目自己维护 |
| [`research/`](./research) | 调研笔记(开放平台能力 / SDK / 鉴权 等) | feishu agent |
| [`decisions/`](./decisions) | ADR(Architecture Decision Record),一文件一决策 | feishu agent |

## 当前状态(2026-05-15)

- **调研**:[`research/approval-integration.md`](./research/approval-integration.md) v0.1 已就位(由 material-storage 调研阶段产出,审批 v4 API + SDK + 鉴权 + 事件,信息相对完备)
- **需求**:[`requirements/from-material-storage.md`](./requirements/from-material-storage.md) v0.1 已就位,包含 6 条需求,P0/P1/P2 优先级标好
- **契约**:**尚未起草**(等 feishu agent 接手)
- **ADR**:**尚未起草**(预期第一篇 ADR-0001:确认走原生审批 v4 API,基于现有调研可以快速落)

## 给 feishu agent 的接手清单

1. 读 [`COLLABORATION.md`](./COLLABORATION.md) 了解协作规则与工作区边界
2. 读 [`research/approval-integration.md`](./research/approval-integration.md) 了解既有调研结论
3. 读 [`requirements/from-material-storage.md`](./requirements/from-material-storage.md) 了解需求清单
4. 起草 [`decisions/0001-approval-channel.md`](./decisions/) 确认走原生审批 v4(应该是橡皮图章,但留个 ADR 痕迹)
5. 起草 [`contracts/approval.md`](./contracts/) 覆盖 MS-FB-001 申请审批 + MS-FB-005 决策路由,PR 让 material-storage agent review
6. 契约 merge 后再启动 `feishu-integration/` 实施
