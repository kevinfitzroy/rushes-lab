# 协作规则(material-storage agent ↔ feishu agent)

本文档定义 **feishu-integration 子项目** 与其上游消费者(目前主要是 **material-storage**)之间的协作机制。两边各由独立的 Claude Code 会话承担(简称 **feishu agent** 与 **material-storage agent**),无法实时通信,唯一可靠的沟通介质是 **git 仓库 + GitHub Issues**。

## 1. 角色与工作区边界

| 实体 | 工作区 | 谁能改 |
| --- | --- | --- |
| 飞书集成实施 | `feishu-integration/` | **仅** feishu agent |
| material-storage 实施 | `material-storage/` | **仅** material-storage agent |
| 飞书方案区(本目录) | `rushes-spec/feishu/` | 见下表 |
| material-storage 方案区 | `rushes-spec/material-storage/` | **仅** material-storage agent |
| 顶层 README / 跨项目共用配置 | `/`、`.gitignore`、`CI` 等 | 双方,但变更必须 PR review |

`rushes-spec/feishu/` 内的细分写权限:

| 子目录 / 文件 | 主导者 | 另一方角色 |
| --- | --- | --- |
| `COLLABORATION.md` | 双方均可改,但**变更必须 PR + 双方 review** | — |
| `contracts/*` | **feishu agent 提案** | material-storage agent **必须 review** 后才能 merge |
| `requirements/from-<upstream>.md` | 上游(如 material-storage)自己写 | feishu agent 拆解、追问、回写"接手状态" |
| `research/*` | feishu agent | 上游可读、可在 PR 提问 |
| `decisions/*`(ADR) | **feishu agent** | 上游可在 PR review,但飞书侧决策由 feishu agent 拍 |

## 2. 主通道:契约 + PR

**契约文件**(`contracts/*.md`)是双方对接的唯一稳定接口。它描述:

- REST 接口的 method / path / request schema / response schema
- 事件 / webhook 的 payload schema
- 错误码枚举
- 状态机
- 版本号(语义化,`v1`, `v1.1`, `v2`)
- 向后兼容承诺

**契约变更流程**:

1. feishu agent(或 material-storage agent 在需求变更时)在一个 feature branch 上修改契约文件
2. 提 PR,**标签 `contract`**;在 PR 描述里说明变更动机与兼容性影响
3. **双方 agent 必须 review 后**才能 merge
4. merged 后契约即冻结;破坏向后兼容的变更**不允许**,需走新版本(`v1` → `v2`,旧版本可暂时并存)
5. 实施代码(`feishu-integration/` 和 `material-storage/`)在契约 merge 后才能调整对接

## 3. 辅助通道:GitHub Issues

GitHub Issues 用于**与具体代码变更解耦的沟通**:

- 问题 / 疑问(`@feishu 这个接口为什么返回 403?`)
- 设计探讨 / 备选方案讨论
- bug 报告
- 长期跟踪事项

**标签约定**(建议在仓库创建以下 label):

| 标签 | 用途 |
| --- | --- |
| `area:feishu` | 飞书侧问题 |
| `area:material-storage` | material-storage 侧问题 |
| `type:contract` | 契约相关讨论 |
| `type:question` | 疑问 |
| `type:bug` | bug |
| `type:design` | 设计探讨 |
| `blocking` | 阻塞另一方工作 |

**分工原则**:能在 PR review 评论里解决的(对具体行号的改动建议、措辞修订),不开 Issue;不能定位到单行的(语义讨论、长期跟踪),开 Issue。

## 4. 决策权

| 决策类型 | 拍板方 |
| --- | --- |
| 飞书侧内部实现(选哪个库、错误处理细节、缓存策略具体值) | feishu agent 自主 |
| 接口契约(method / path / schema / 错误码) | **双方共识**,必须 PR |
| 破坏向后兼容的契约变更 | **不允许**,只能走新版本契约 |
| material-storage 是否要某个新需求 | material-storage agent / 用户 |
| 是否值得新增一项飞书能力(超出现有需求) | 用户(双方都不能擅自扩范围) |

## 5. 用户直接对话的同步要求

> ⚠️ **关键规则:** 用户可能在某一会话里直接和某个 agent 对话,产生新决策(例如"把审批超时改成 48 小时")。**该 agent 必须把决策回写到 `rushes-spec/feishu/` 的相应文件**(契约、需求、ADR 或 COLLABORATION.md),否则另一个 agent 看不到,会出现两边失同步。

具体落地:

- 若用户说"我要改 X 需求" → material-storage agent 编辑 `requirements/from-material-storage.md`,加 changelog
- 若用户说"飞书侧用 Y 实现" → feishu agent 编辑 `decisions/` 加 ADR 或 `research/` 加补充
- 若用户说"协作规则改 Z" → 编辑本文件,提 PR,让对方 review

## 6. 起手包(feishu agent 接手时按这个顺序读)

1. **本文件** —— 协作规则
2. [`README.md`](./README.md) —— 方案区索引
3. [`research/approval-integration.md`](./research/approval-integration.md) —— 既有调研结论(审批 v4 API、SDK 评估、鉴权策略)
4. [`requirements/from-material-storage.md`](./requirements/from-material-storage.md) —— 需求清单
5. 仓库顶层 [`/CLAUDE.md`(local)](../../../CLAUDE.md)(如果存在)+ [`/README.md`](../../README.md)
6. **首要交付物:** ADR-0001(走原生审批 v4 的决策痕迹)+ contract `contracts/approval.md`(对应 MS-FB-001 / MS-FB-005)

## 7. 上游接手时(material-storage agent 评估契约)

material-storage agent 收到 feishu agent 的契约 PR 时需要:

- 验证 schema 覆盖 `requirements/from-material-storage.md` 中相应需求项的"期望行为"
- 检查错误码是否够用(material-storage 侧 UX 需要哪些错误分支)
- 检查同步/异步语义(有没有用上"事件 vs 回调"的区分)
- 评估幂等性 / 重试语义(尤其是事件 webhook)
- 在 PR comment 里逐点 review,通过则 approve + merge

## 8. 仓库结构速查

```
rushes-lab/
├── feishu-integration/                  ← feishu agent 实施
├── material-storage/                    ← material-storage agent 实施
└── rushes-spec/
    ├── feishu/                          ← 本目录
    │   ├── COLLABORATION.md             ← 本文件
    │   ├── README.md
    │   ├── contracts/                   ← 契约文件(双方接口)
    │   ├── requirements/                ← 上游需求(material-storage 等)
    │   ├── research/                    ← 飞书侧调研
    │   └── decisions/                   ← 飞书侧 ADR
    └── material-storage/                ← material-storage 方案区
```
