# rushes-spec

方案细化与决策记录的统一工作区。每个目标系统/项目在本目录下开一个**作用域文件夹**(scope folder),内含该项目的开放问题、调研笔记、决策记录(ADR)与最终方案。

> 实施代码 vs 方案设计:实施落在仓库根的对应 `<project>/` 目录(如 `material-storage/`);方案讨论与决策痕迹留在这里 `rushes-spec/<project>/`。两边通过项目名一一对应。

## 当前作用域

| Scope | 状态 | 索引 |
| --- | --- | --- |
| `material-storage/` | 方案细化中(v2 初稿) | [./material-storage/README.md](./material-storage/README.md) |
| `feishu/` | 方案就位,等独立 agent 接手实施 | [./feishu/README.md](./feishu/README.md) |

## 内容约定

每个 scope 文件夹建议结构(按需创建,不必一开始就全建):

```
rushes-spec/<scope>/
├── README.md           # 索引:开放问题、决策清单、调研清单
├── decisions/          # ADR(Architecture Decision Record),一文件一决策
│   └── NNNN-<slug>.md
├── research/           # 调研笔记,一议题一文件
│   └── <topic>.md
└── open-questions.md   # 滚动维护的待决清单(可选)
```

### ADR 文件命名

`decisions/NNNN-<slug>.md`,NNNN 是 0001 起的零填充编号,slug 用 kebab-case。建议含以下小节:背景 / 候选 / 决策 / 影响 / 状态(proposed / accepted / superseded)。

### 调研笔记

不强制模板。但每篇笔记应在文首给一行结论(TL;DR)和调研日期,以便后续回看。

## 不进仓库的内容

- 公司具体业务描述、客户/业务方/品牌名、内部文件路径、敏感参数
- 原始方案 docx / 内部文档 —— 保留在工作区本地的 `refs/` 下,**不复制进来**
- 仅在 spec 中保留**通用化、技术化**的提炼(候选技术、对比维度、决策依据)
