# 协作规则(material-storage tester agent ↔ 开发 agent)

本文档定义 **material-storage 测试反馈 agent** 与 **开发 agent** 之间的协作机制。两边各由独立的 Claude Code 会话承担,无法实时通信,唯一可靠的沟通介质是 **GitHub Issues**。

本文是给 **tester agent** 看的契约 —— 告诉它如何交付合格的反馈,让 dev 能直接进入修复,而不需要回头追问。

> 平级 agent 协作(如 material-storage ↔ feishu)的契约见 [`../feishu/COLLABORATION.md`](../feishu/COLLABORATION.md)。本文只覆盖 tester ↔ dev。

## 0. TL;DR(一分钟版)

| What | How |
| --- | --- |
| 通道 | **GitHub Issues**(`gh issue create --template <name>`) |
| 反馈类型 | `[bug]` / `[feat]` / `[ui]`(标题前缀 + 对应 template) |
| 不要做 | 写代码 / 提 PR / 改 server2 / 删别人数据 / paste 敏感信息 |
| 文字 vs 截图 | **文字是必须**(URL / 控制台 / network / 步骤); 截图仅 UI 视觉问题辅助,必须配 caption |
| Lifecycle | tester 提 → dev 修 + 贴 PR → tester 复测 → **tester 关 issue** |

## 1. 角色与边界

| 实体 | 工作内容 |
| --- | --- |
| **dev agent** | 修代码 / 写 PR / 部署到 server2 / 维护契约 |
| **tester agent** | 浏览 UI、上传下载、申请审批、创建项目;**用产品**;**提 issue** |

### tester agent **不能**做的事

- ❌ 写代码、提 PR、改任何代码文件(包括 `rushes-spec/`、`material-storage/`、`.github/`)
- ❌ 直接 ssh/docker/nginx 操作 server2(8.156.34.238)
- ❌ 删除别的用户创建的 project / folder / asset
- ❌ 批量破坏性操作:一次上传 > 100 个文件、单文件 > 100MB、批量删除
- ❌ 在 issue / comment 里 paste 真实敏感信息(见 §4)
- ❌ 关 issue —— 除了**复测通过后关自己提的 issue**(见 §7)

### tester agent **应该**做的事

- ✅ 当真实用户用,golden path + edge case 都跑
- ✅ 发现可疑行为时 **先复现一次**(确认不是 flake)
- ✅ 提 issue 前 **先搜重**(见 §2)
- ✅ 提 issue 时 **走 template**(见 §3)
- ✅ dev 给 PR + 部署后 **复测 + 关 issue**(见 §7)

## 2. 提 issue 前必做:搜重 + 查已知坑

### 2.1 搜重

```bash
# 关键词搜全部 issue(open + closed)
gh issue list --search "<keyword>" --state all --limit 20

# 例:报"上传卡住"前先看
gh issue list --search "上传 卡" --state all
gh issue list --search "upload stuck" --state all
```

如果找到同样症状的 open issue → **在原 issue 加 comment**(`gh issue comment <num> --body "..."`),提供新的复现信息。**不要开新 issue**。

如果是 closed 但症状复发 → **开新 issue,在描述里 reference 旧 issue**(`见 #<num>,closed 后复发`)。

### 2.2 已知坑(不要重复报)

dev 已经知道、在 backlog 里、或决定不修的事项,见:

- [`ROADMAP.md`](./ROADMAP.md) "已知坑" 章节
- [`ops-manual.md`](./ops-manual.md) "关键事实" 章节
- `gh issue list --state open --label "type:task"` —— 已规划任务

如果你怀疑的问题在以上任一处出现过,**先 comment 已有 issue,不要新开**。

## 3. Issue 类型与必填字段

三类 issue,各有 template。**走 template,不要写自由格式**。

### 3.1 `[bug]` —— 现有功能行为不对

标题:`[bug] <一句话症状>` (例:`[bug] 上传 mp4 后缩略图始终不生成`)

Template:`bug.yml`

必填:

| 字段 | 说明 |
| --- | --- |
| **复现步骤** | 数字编号,从干净状态开始(eg. "1. 登录 → 2. 进入项目 X → 3. 点上传 ...") |
| **期望行为** | 一句话 |
| **实际行为** | 一句话 |
| **复现率** | `必现` / `偶发 N/M`(例 `偶发 2/5`) / `仅 1 次` |
| **严重度** | `blocker`(无法工作) / `major`(主要功能挂) / `minor`(workaround 可用) / `nit`(美观/文案) |
| **环境** | server2 URL / 本地;浏览器版本;**当前登录用户角色**(sysadmin / project admin / uploader / downloader / viewer) |
| **App 版本** | server2 浏览器地址栏 + 时间,或后端 commit sha(见 §5.2) |
| **控制台错误** | F12 → Console;**文字 code-fence**,不要截图(见 §4) |
| **网络请求** | F12 → Network,失败请求的 URL + status + response body;**文字** |

可选:

- **截图**(强制 caption,见 §4)
- 影响范围(只我自己 / 所有人 / 仅某角色)

### 3.2 `[feat]` —— 新功能想法

标题:`[feat] <一句话能力>` (例:`[feat] 项目卡片支持自定义封面图`)

Template:`feature.yml`

必填:

| 字段 | 说明 |
| --- | --- |
| **用户故事** | "作为 <角色>,我希望 <能力>,从而 <价值>" |
| **当前 workaround** | 没有这个功能时怎么绕过(或"无 workaround,blocking") |
| **优先级建议** | `nice-to-have` / `should-have` / `must-have` |

可选:

- 相关 issue / PR 链接
- 类似产品参考(Frame.io / Linear / Notion / ...)

### 3.3 `[ui]` —— UI / 视觉 / 体验改进

标题:`[ui] <一句话>` (例:`[ui] 项目列表卡片在移动端文字溢出`)

Template:`frontend-feature.yml`

必填:

| 字段 | 说明 |
| --- | --- |
| **页面 / 组件** | 路由 URL + 组件名(例 `/projects` ProjectsPage.tsx) |
| **当前现象** | 文字描述(截图作为辅助) |
| **期望效果** | 文字描述(可参考其他产品 / 附设计稿) |
| **设备 / 端** | desktop / mobile / 飞书 webview;具体分辨率 |
| **是否影响其他端** | 改完后 mobile / webview 是否会受影响 |

可选:

- 截图(强制 caption)
- 视觉参考图

## 4. 截图与敏感信息处理 ⚠️

### 4.1 文字 vs 截图 —— 文字优先

**文字必须存在**。截图**不能代替**以下任何内容:

| 内容 | 必须文字 | 原因 |
| --- | --- | --- |
| URL | ✅ | dev 要能复制 |
| 控制台 error / stack trace | ✅ | greppable,dev 要在代码里搜 |
| 网络请求 URL / status / response body | ✅ | 同上 |
| 复现步骤 | ✅ | AI agent 解析图片不可靠 |
| 期望 / 实际行为 | ✅ | 要能搜重 |

**截图仅作为辅助**,适用场景:

- UI 视觉问题(布局错位、配色不对、字体糊)
- 难以用文字描述的交互(动画卡顿、抖动)

### 4.2 截图规则(如果加截图)

- **必须配 caption**:一句话说明"图里发生了什么 / 看哪里"
  - ✅ `图1:项目卡片在 375px 宽度下,创建时间被截断`
  - ❌ (只贴图无说明)
- **大小 ≤ 2MB**;超过请压缩或改为文字描述
- **格式**:PNG / JPG / WebP
- **上传方式**:直接拖拽到 GitHub Issue 编辑框(会生成 `user-images.githubusercontent.com/...` URL);**`gh` CLI 提 issue 时无法直接 paste 图**,如果非加图不可,可以:
  1. 先 `gh issue create` 开 issue
  2. 再 `gh issue edit <num>` 或在网页加图
  3. 或者描述够清晰就不加图(**这是合法的**)

### 4.3 敏感信息 —— 严禁上传

material-storage 是医美素材库,真实数据 **极度敏感**。以下信息 **绝不可** 出现在 issue / comment / 截图中:

| 类型 | 处理 |
| --- | --- |
| 顾客真实姓名 | → "顾客A"、"测试客户1" |
| 顾客手机号 | → "138****1234" 或 "phone-redacted" |
| 顾客身份证 | → 完全删除 |
| **顾客术前 / 术中 / 术后照片** | **不上传任何形式**;描述即可(eg. "顾客面部 close-up,有红斑") |
| 内部员工真实 open_id | OK(open_id 本身不敏感,但避免大批量列举) |
| 内部员工手机 / email | → 部分脱敏 |
| 公司财务 / 价格 / 客户数 | → 不要 paste |

**截图前必检查**:

- [ ] 没有顾客面部 / 身体特征
- [ ] 没有真实手机号 / 姓名 / 价格
- [ ] AssetTable 里的文件名脱敏(`张三术前.jpg` → "测试文件.jpg")

发现已 paste 的敏感信息 → **立刻 `gh issue edit <num>` 删除**,然后告诉 dev "已删,但要清 GitHub edit history"(dev 会处理)。

## 5. App 版本与环境识别

### 5.1 环境枚举

| 环境 | URL | 说明 |
| --- | --- | --- |
| **server2 dev** | `http://8.156.34.238/ms-static/web` | 团队共享 dev 实例,默认在此测 |
| 本地 web | `http://localhost:5173` | 本地开发,通常不归 tester |
| 本地 api | `http://localhost:8000` | 同上 |
| **飞书 webview** | 飞书 App → 工作台 → material-storage | UA 不同,需单独测移动端兼容 |

issue 必须写明 **哪个环境**。同一个 bug 在 server2 复现,本地不复现,本身就是关键信息。

### 5.2 拿 App 版本

**前端**:浏览器地址栏 + 截图时间。如果有 build hash 显示,贴上。

**后端**:

```bash
# tester agent 通常无 server2 ssh 权限。如果无法拿到 sha,在 issue 写:
# "提交时间: 2026-05-17 14:30 CST"
# dev 会根据时间反查 commit
```

如果 tester agent 恰好有权访问,可以问 dev 帮取 sha。**不要自己 ssh server2 跑命令。**

## 6. Labels

仓库 label 一览:`gh label list`

template 会自动打这些 label,**tester 不需要手动加**:

- `bug.yml` → `bug` + `area:material-storage`
- `feature.yml` → `enhancement` + `area:material-storage`
- `frontend-feature.yml` → `enhancement` + `area:material-storage`

**优先级 label**(`priority:p1` 等)由 dev triage 时打,tester 不打 —— tester 在正文写"严重度"即可(§3.1 表)。

**`blocking`** label:仅当问题阻塞 tester 后续测试时打。

如果发现需要新 label(例如 `area:web` vs `area:api` 区分),**先在 issue 里建议**,dev 同意后由 dev 创建:

```bash
gh label create "area:web" --description "前端 (Vite/React) 相关" --color "1d76db"
```

## 7. Lifecycle —— 谁开、谁关、什么时候关

```
   tester                               dev
     │
     │  1. 复现 + 搜重 + 提 issue (template)
     │ ────────────────────────────────►│
     │                                   │
     │                                   │  2. triage:打 priority label / 分配 / 拒绝
     │                                   │  3. 修 → 开 PR → merge → 部署到 server2
     │  4. comment: "fixed in PR #N,    │
     │              deployed <时间>"    │
     │ ◄────────────────────────────────│
     │                                   │
     │  5. 复测(原步骤重跑)             │
     │     ├─ ✅ 通过 → 关 issue          │
     │     │      gh issue close <N> \   │
     │     │        --comment            │
     │     │        "verified on <env>, │
     │     │         commit <sha>"      │
     │     └─ ❌ 不通过 → comment "未通过,│
     │            <新现象>" + 重开        │
```

**关键**:

- **dev 不关 issue**;dev 只贴 PR + "已部署"。**关 issue 是 tester 的复测确认动作。**
- tester 复测通过 → **必须留 verify comment**(写明环境 + sha 或时间),不能空关
- 如果 dev 部署后 1 周 tester 没回复,dev 可以 comment 催;再 1 周无回复 dev 可自行关(写明"无 verify 反馈,默认关闭")

## 8. gh CLI 速查

```bash
# 搜重
gh issue list --search "<keyword>" --state all

# 看自己提的 issue
gh issue list --author "@me" --state all

# 提 bug(走 template)
gh issue create --template bug.yml

# 提 feature
gh issue create --template feature.yml

# 提 ui
gh issue create --template frontend-feature.yml

# 给已有 issue 加 comment
gh issue comment <num> --body "$(cat <<'EOF'
...多行内容...
EOF
)"

# 关自己 issue + verify
gh issue close <num> --comment "verified on server2, 2026-05-17 14:30 CST"

# 看 dev 给的 PR
gh pr view <pr-num>
```

**长 body 用 heredoc**(终端 wrap 会截断 `--body` 后的长字符串):

```bash
gh issue create --template bug.yml --title "[bug] foo" --body "$(cat <<'EOF'
## 复现步骤
1. ...
2. ...
EOF
)"
```

## 9. 反例:不合格的反馈(dev 会要求重写)

❌ **纯截图无文字**:`<screenshot.png>`(只有图,没有任何文字)

❌ **无复现步骤**:`上传不行` (没说怎么复现,什么文件,什么角色)

❌ **截图代替控制台**:`<screenshot 显示 console error>` (应该 paste 文字)

❌ **多个不相关问题**:`bug1: 上传慢;bug2: 卡片样式差;bug3: 登录失败` (拆 3 个 issue)

❌ **重复已有 issue**:`上传卡住`(没搜重,#42 已存在)

❌ **paste 顾客照片**:`这是上传失败的图:<顾客术前照>` (违反 §4.3,立刻删)

❌ **关闭别人的 issue** 或 **不留 verify 关自己的 issue**

## 10. 文档变更

本文件变更走 PR + dev review。tester agent 不直接编辑本文件;有改进建议 → 开 `[feat]` issue,正文写"建议更新 COLLABORATION.md §X 为 ..."。
