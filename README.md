# rushes-lab

团队工程与资料汇总仓库,采用 **多项目 monorepo** 布局:每个项目独立成一个顶层目录,构建/测试/依赖配置都收敛在各自项目内。

## 项目目录

| 项目 | 说明 | 状态 |
| --- | --- | --- |
| [`rushes-spec/`](./rushes-spec) | 方案细化与决策记录工作区(各项目的 ADR / 调研笔记 / 契约) | 进行中 |
| [`material-storage/`](./material-storage) | 素材存储系统(实施目录) | 规划中,方案见 `rushes-spec/material-storage/` |
| [`feishu-integration/`](./feishu-integration) | 飞书集成桥接层(对内 REST,对外飞书开放平台) | 规划中,由独立 agent 接手,见 `rushes-spec/feishu/COLLABORATION.md` |

> 新增项目:在仓库根目录下创建一个项目子目录,初始化各自的 `README.md` 与构建配置,再把它加入上表。

## 仓库约定

- **不要**把项目级的依赖/构建脚本(`package.json`、`pyproject.toml`、`Cargo.toml` 等)放到仓库根目录;它们属于各项目目录。
- 仓库根只放跨项目共用资产:本 `README.md`、`.gitignore`、CI 配置、贡献说明等。
- 私有密钥、`.env` 与本地参考资料**不要进仓库**(已在 `.gitignore` 中过滤一部分,但提交前请自查)。
