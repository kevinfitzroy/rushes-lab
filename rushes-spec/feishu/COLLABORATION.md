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

## 9. Git 操作互斥 lock + 分支自检(2026-05-15 加,事故后引入)

两个 agent 在共享 cwd 操作 git 会互相干扰 —— 已发生过 main 分支意外污染 + commit 落到对方分支上的事故(详见 §9.5)。本节定义协作 lock 机制 + commit 前必跑的自检清单。

### 9.1 互斥 lock 文件

**路径(相对仓库根):** `.claude/agent-locks/git.lock`

> `.gitignore` 已覆盖 `.claude/`,**不入仓库**,仅在本地 cwd 生效。

**格式:** 单行 `<agent-name>:<unix-timestamp>:<reason>`,例如:

```
material-storage:1715789012:rebase + commit v0.4 file-management-system update
```

**Agent name 约定:**

- material-storage agent → `material-storage`
- feishu agent → `feishu`

### 9.2 何时获取 lock

**必须**获取 lock 的 git 操作(写动作):

- `git checkout <branch>` / `git switch`(切分支)
- `git branch -f` / `git reset` / `git rebase` / `git merge`
- `git cherry-pick` / `git revert` / `git apply`(改 HEAD)
- `git commit` / `git commit --amend`
- `git push`(任何形式)
- `git stash push` / `git stash pop`
- `git clean -fd` / `git restore`(改 working tree)
- `git tag` / `git tag -d`(改 ref)

**不需要** lock 的 git 操作(只读 / 不影响 HEAD):

- `git status` / `git log` / `git diff` / `git show`
- `git fetch`(只更新 remote-tracking,不动本地 ref)
- `gh pr view` / `gh pr diff` / `gh issue list` 等远端只读

### 9.3 协议

```
0. (session 起手清理)如果 lock 内容是自己 agent name → rm -f
   (孤儿 lock — 同一 agent 的上次 session crash/forget;**假设同一 agent 不并行多 session**)
1. mkdir -p .claude/agent-locks
2. 读取 .claude/agent-locks/git.lock(不存在 → 视为空 lock)
3. 判定:
   - 不存在 / 时间戳 > 60 分钟前 → 失效,可抢
     (60 min 而非 30 min:advisor 校对 + 起草 + commit + push 这种链路就接近 30 min,
      预留 buffer)
   - 内容是自己 agent name → 已持有,可直接进行 + 续约 timestamp
   - 内容是别人 agent name + 未过期 → **STOP,告知用户**:
     "git lock 被 <other-agent> 持有(since <timestamp>, reason: <reason>),
      请协调或在 <other-agent> 会话中释放 lock"
4. 抢锁:atomic write `<self>:<now>:<reason>` 到 .claude/agent-locks/git.lock
   实施:`echo "..." > .claude/agent-locks/git.lock.tmp && \
          mv .claude/agent-locks/git.lock.tmp .claude/agent-locks/git.lock`
5. 执行 git 操作
6. 操作后失败/成功语义:
   - 正常完成 → `rm -f .claude/agent-locks/git.lock`(释放)
   - **失败但状态未损**(参数错 / 网络错 / push 被拒)→ `rm -f`(释放,失败 op 不污染下次)
   - **状态损坏**(merge conflict / rebase in progress / cherry-pick conflict)→
     **保留 lock + STOP + 告知用户介入**(`git status` 会显示有 unmerged paths;
     用户处理完后 release lock)
```

### 9.4 Commit 前自检清单(必跑)

每次 `git commit` 之前,**显式 verify** 四件套:

```bash
echo "branch:   $(git symbolic-ref --short HEAD)"
echo "email:    $(git config user.email)"
echo "lock:     $(cat .claude/agent-locks/git.lock 2>/dev/null || echo 'not held')"
echo "tree:     $(git status --porcelain | wc -l | xargs) modified path(s)"
```

预期:

- **`branch:`** 是你打算 commit 到的分支(**不**是 `main`,**不**是对方 agent 的 `feat/<other>-*` 分支)— **不符 → STOP**
- **`email:`** 严格等于 `kevinfitzroy715@gmail.com`(workspace memory: git-identity-isolation;**严禁** zklink 邮箱)— **不符 → STOP**
- **`lock:`** 应该是 `<self>:<recent-ts>:<reason>`(自己持有 lock)— **不符 → STOP**
- **`tree:`** 显示 modified 路径数 — 若 > 你即将 commit 的文件数,说明 working tree 有他方未 commit 的改动 → **warn(不强制 STOP)**:确认这些改动**不属于本次 commit**;用 `git add <specific-paths>` 而**非** `git add -A` 来避免误 commit 他方文件

任一前三项不符 → STOP;第四项 warn 后可继续(用具体路径 `git add`)。

### 9.5 历史事故(2026-05-15)

material-storage agent 在 `git rebase main` 后,HEAD 意外落在 feishu agent 的本地分支 `feat/feishu-contract-identity-v1`(飞书 agent 已切到但未提交)。结果:material-storage agent 的 PoC commit 加错分支 + local main 被污染。

**修复:** reset 受影响分支 → cherry-pick commit 到正确分支 → fast-forward push。

**根因:** 共享 cwd 无 lock + commit 前无 branch verify。本节是事故后引入的协作规则。

### 9.6 推荐立即采纳:git worktree

worktree 是**硬隔离**(两 HEAD 物理分离),lock 是**软约束**(协议靠 agent 自律)。本节为推荐立即采纳路径;§9.1-9.5 lock 协议作 fallback,适用于 worktree 因故未启用的会话(例如临时 ad-hoc 操作)。

```bash
# 在 workspace 根目录(假设 rushes-lab/ 已 clone)
cd /Users/foxer/claude/rushes-lab-workspace
git -C rushes-lab worktree add ../rushes-lab-feishu
```

- material-storage agent cwd:`.../rushes-lab-workspace/rushes-lab/`
- feishu agent cwd:`.../rushes-lab-workspace/rushes-lab-feishu/`

两 worktree 共享 `.git` 对象库(同 remote / push / fetch),但**各自独立 HEAD**,git 操作不可能跨界。

**用户操作指引**:在两个 Claude Code 会话启动时,显式 `cd` 到对应目录(`.../rushes-lab/` 给 material-storage agent;`.../rushes-lab-feishu/` 给 feishu agent)。引导语已相应调整(见仓库根 `README.md`)。

worktree 启用后,§9.1-9.5 的 lock 协议**仍保留为协议**(供 ad-hoc 场景使用),但实际共享 HEAD 风险降到 0。
