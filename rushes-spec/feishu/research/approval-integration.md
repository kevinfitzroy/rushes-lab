# 调研:飞书(Feishu / Lark)审批对接

> **调研日期:** 2026-05-15
> **版本:** v0.1
> **迁移说明:** 2026-05-15 由 `rushes-spec/material-storage/research/feishu-approval.md` 迁入(`git mv` 保留 history)。原属 material-storage 调研区,因飞书功能拆为独立子项目 `feishu-integration`,此文档归位到飞书方案区,供 **feishu agent** 接手时作为调研起点。文中 §13 "待办" 是 feishu agent 的工作清单。
> **结论摘要:** 推荐走 **飞书原生审批 v4 API**(`/open-apis/approval/v4/*`),不走"三方审批实例同步"。鉴权用 `tenant_access_token` + Redis 中心化缓存。Python 用官方 `lark-oapi` SDK 处理 token / 事件 / 卡片回调 / 加解密,审批 API 调用以"低层封装 + 手写参数"为主(SDK 高层未覆盖审批模块的现成示例)。
> **状态:** v0.1 草稿,基于 open.feishu.cn 官方文档与 SDK README 一手证据

## 1. 调研范围(用户指定)

| 角度 | 是否覆盖 | 章节 |
| --- | --- | --- |
| 审批引擎本身的能力 | ✅ | §2、§5 |
| 开放平台 API / 文档 / SDK 质量 | ✅ | §5、§9 |
| 身份 / 通讯录 / 机器人 / 消息卡片 等边边能力 | ✅ | §7、§8、§9 |
| 应用商市场 / 自建应用上架审核 | ❌(用户未选) | — |

## 2. 集成路径对比

飞书提供**两条并存但截然不同**的集成路径:

| 维度 | 原生审批 v4 (`/open-apis/approval/v4/*`) | 三方审批实例同步 (`/approval/openapi/v2/external/*`) |
| --- | --- | --- |
| 工作流引擎在哪 | **飞书侧** | **我方系统侧** |
| 我方角色 | 通过 API 创建审批定义和实例;接收状态变更事件 | 我方维护审批工作流;只是把实例/任务/抄送同步到飞书做展示 |
| 用户操作位置 | 飞书审批中心 | 飞书审批中心列表 →**跳转回我方系统**操作 |
| UI / 通知 | 飞书原生承包 | 列表展示靠飞书,详情/操作页面靠我方 |
| 撤销/转交/加签 | 原生支持 | 我方实现,飞书侧同步状态 |
| 适合 | 没有现成审批系统、想让飞书做"统一审批中心" | 已有完整审批系统、要把它接入飞书 |
| 适合 material-storage? | ✅ | ❌(我方没有现成审批系统,自建反而徒增成本) |

**结论:走原生审批 v4**。`material-storage` 没有也不需要自建审批工作流引擎,把工作流交给飞书最省事。

## 3. 推荐方向:飞书原生审批 v4

### 3.1 端到端时序(资源下载审批场景)

```
申请人                FastAPI                 飞书审批 v4 API           飞书审批中心        审批人
  │                    │                          │                       │              │
  │ 1.申请下载         │                          │                       │              │
  │──────────────────▶│                          │                       │              │
  │                    │ 2.取 tenant_access_token │                       │              │
  │                    │ (Redis 缓存命中或刷新)   │                       │              │
  │                    │─────────────────────────▶│                       │              │
  │                    │◀─────────────────────────│                       │              │
  │                    │                          │                       │              │
  │                    │ 3.POST /v4/instances     │                       │              │
  │                    │   (approval_code + 表单) │                       │              │
  │                    │─────────────────────────▶│                       │              │
  │                    │◀── instance_code ────────│                       │              │
  │                    │                          │                       │              │
  │                    │ 4.插入 ApprovalRecord   │                       │              │
  │                    │   (status=PENDING)       │                       │              │
  │ 5.申请已提交       │                          │                       │              │
  │◀──────────────────│                          │                       │              │
  │                    │                          │ 6.推送审批任务         │              │
  │                    │                          │──────────────────────▶│ 7.审批人操作 │
  │                    │                          │                       │◀─────────────│
  │                    │                          │                       │              │
  │                    │                          │ 8.事件回调             │              │
  │                    │                          │   (审批实例状态变更)   │              │
  │                    │◀─────────────────────────│                       │              │
  │                    │                          │                       │              │
  │                    │ 9.验签 + 解密 + 更新     │                       │              │
  │                    │   ApprovalRecord         │                       │              │
  │                    │   状态机                 │                       │              │
  │                    │                          │                       │              │
  │ 10.通过/拒绝通知   │                          │                       │              │
  │◀──────────────────│                          │                       │              │
  │                    │                          │                       │              │
  │ 11.下载(若通过):  │                          │                       │              │
  │    走 FastAPI 代理 │                          │                       │              │
  │    端点 + 临时签名 │                          │                       │              │
  │    URL             │                          │                       │              │
  │◀──────────────────│                          │                       │              │
```

### 3.2 状态机

| 飞书 instance 状态 | 我方 ApprovalRecord 状态 | 触发条件 |
| --- | --- | --- |
| PENDING | `submitted` / `approving` | 创建成功 / 审批人收到 |
| APPROVED | `approved` | 全部审批人通过 |
| REJECTED | `rejected` | 任一审批人拒绝(默认串行) |
| CANCELED | `withdrawn` | 申请人撤销 |
| DELETED / HIDDEN | `archived` | 审批被管理员删除/隐藏 |

## 4. 关键 API 清单

| 用途 | 接口 | 备注 |
| --- | --- | --- |
| 创建审批定义(模板) | `POST /open-apis/approval/v4/approval` | 也可在飞书审批后台 `devMode=on` 用 UI 配置取 `approval_code`,**初期推荐 UI 配置**,迭代后再代码化 |
| 创建审批实例 | `POST /open-apis/approval/v4/instances` | 必填 `approval_code` + 表单字段值 + 审批人 |
| 查询实例 | `GET /open-apis/approval/v4/instances/:instance_id` | 详情 + 状态 + 任务链 |
| 批量列实例 | `GET /open-apis/approval/v4/instances` | |
| 查询我的任务 | `GET /open-apis/approval/v4/tasks/query` | 通常给"待办面板"用 |
| 任务搜索 | `POST /open-apis/approval/v4/tasks/search` | |
| 撤销 | `POST .../instances/cancel` | |
| 转交 | `POST .../tasks/transfer` | |
| 加签 | `POST .../tasks/add_sign` | |
| 抄送 | `POST .../instances/cc` | |
| 评论 | `POST .../instances/:instance_id/comments` | |
| 文件上传(附件) | `POST /approval/openapi/v2/file/upload` | **注意 v2 路径**,不是 v4,容易踩 |

关键标识符:
- `approval_code`:审批定义(模板)的唯一 ID
- `instance_code` / `instance_id`:单次审批申请的 ID
- `task_id`:实例中某个审批人的具体任务

## 5. 鉴权:`tenant_access_token`

### 5.1 获取

```
POST https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal
Content-Type: application/json

{
  "app_id": "cli_xxxx",
  "app_secret": "xxxx"
}
```

返回:
```json
{
  "code": 0,
  "msg": "ok",
  "tenant_access_token": "t-xxxx",
  "expire": 7200
}
```

### 5.2 刷新与缓存策略

- 默认有效 **2 小时**(7200s)
- 官方推荐:**剩余 < 30 分钟时刷新**;新旧 token 一段时间内并存有效(平滑切换)
- **多实例部署必须中心化缓存**(Redis),否则各实例独自刷新会浪费并被限频

推荐实现:
```python
# 伪代码
def get_tenant_access_token():
    cached = redis.get("feishu:tat")
    if cached and ttl(cached) > 1800:  # > 30 min
        return cached
    # 上锁避免雪崩刷新
    with redis.lock("feishu:tat:refresh", timeout=10):
        cached = redis.get("feishu:tat")  # 双检
        if cached and ttl(cached) > 1800:
            return cached
        new = call_internal_api()
        redis.setex("feishu:tat", new.expire - 60, new.token)
        return new.token
```

### 5.3 `tenant_access_token` vs `app_access_token` vs `user_access_token`

| 凭证 | 前缀 | 用途 | 有效期 |
| --- | --- | --- | --- |
| `tenant_access_token` | `t-` | **自建应用代表企业调用 API(99% 场景)** | 2h |
| `app_access_token` | `a-` 或 `t-` | 商店应用代表应用本身调用,少数 API 需要 | 2h |
| `user_access_token` | `u-` | 代表具体用户调用(网页 OAuth 授权后) | 6900s |

material-storage 场景中:
- 99% 调用用 `tenant_access_token`
- 网页授权拿用户身份(open_id 映射)时用 `user_access_token`

## 6. 事件订阅 vs 同步回调

飞书把这两件事**明确分开**:

| 类型 | 用途 | 响应时限 | 重试 |
| --- | --- | --- | --- |
| **事件**(异步) | 状态变更通知,如审批实例状态变更 | 3 秒内 HTTP 200 | 失败重试 4 次,间隔 15s / 5min / 1h / 6h |
| **回调**(同步) | 卡片交互、三方审批实例同步等需要业务侧立即返回内容 | 立即返回结构化数据 | 一般不重试 |

**审批走"事件"**,我方 webhook 必须:
- **幂等**(重试 4 次会重投同一事件)
- 3 秒内返回 200,重业务放进队列异步处理
- 验签(`Verification Token`)+ 解密(`Encrypt Key`,可选但生产环境必启)

事件类型清单(审批相关):
- 审批实例状态变更
- 审批任务状态变更(单个审批人)
- 审批抄送状态变更

## 7. 用户身份与通讯录

### 7.1 三种 user id

| ID | 作用域 | 推荐 |
| --- | --- | --- |
| `open_id` | **应用级**(本应用看到的用户匿名 id) | ✅ 默认用这个 |
| `user_id` | 企业级(通讯录里的 short id) | 通讯录关联时用 |
| `union_id` | 跨应用关联同一用户 | 多应用场景才需要 |

material-storage 是单一自建应用 → **`open_id` 够用**。

### 7.2 用户身份获取流程

我方 Web UI 让员工"用飞书登录":
1. 前端跳转飞书授权 URL(`/open-apis/authen/v1/index`),scope = `contact:user.base:readonly`
2. 用户授权后回调到我方 `/oauth/callback?code=...`
3. 我方后端用 `code` 换 `user_access_token`(POST `/open-apis/authen/v1/access_token`)
4. 拿 `user_access_token` 调 `/open-apis/authen/v1/user_info` 获取 `open_id`
5. 我方 DB 建 `user_mapping(internal_user_id, feishu_open_id)`,首次绑定后持久化

### 7.3 通讯录同步

如果要**主动拉取部门架构 / 全员清单**(支撑审批人选择 / 角色映射):
- 用 `tenant_access_token` 调 `/open-apis/contact/v3/departments/*` 和 `/users/*`
- 需要在开发者后台申请"通讯录"权限范围
- 推荐:定时(每日)全量同步 + 通过事件"员工变更"做增量

## 8. SDK 评估:`lark-oapi` (Python)

| 维度 | 评价 |
| --- | --- |
| 仓库 | `github.com/larksuite/oapi-sdk-python`,**官方维护** |
| 活跃度 | 持续更新,issues / PRs 活跃 |
| 覆盖度 | 消息、通讯录、日历、群组、Drive 等核心模块**有高层封装**;审批模块**官方 README 未列示例**,实测要用通用调用层手写参数 |
| 鉴权 | **内置** `tenant_access_token` / `app_access_token` 自动获取与缓存(单进程) |
| 事件订阅 | ✅,Flask 集成示例齐 |
| 卡片回调 | ✅,独立模块,支持返回新卡片 JSON |
| 加解密 | ✅,配置 `EncryptKey` + `VerificationToken` |
| 推荐模式 | HTTP 服务器(Flask/类 ASGI)长跑接收 webhook;不适合纯 serverless 单次执行 |
| 风险点 | 内置 token 缓存是**进程内**,**多实例部署仍要外挂 Redis 缓存层**(见 §5.2);否则每个进程独自刷新 |

**结论:** SDK 用其鉴权 / 事件 / 卡片 / 加解密,审批 API 用 `client.request()` 通用调用层手写;不依赖 SDK 高层封装。

## 9. 消息卡片与机器人(支撑能力)

- **消息卡片**(交互卡片):富文本 + 按钮 + 表单,推送到群或个人;按钮点击会触发**同步回调**(见 §6),适合"轻量审批 / 内部确认 / AI 推荐确认"等小流程
- material-storage 场景的可能用法:
  - 审批人收到飞书审批通知后,在卡片里直接点"通过/拒绝"(这是飞书审批中心原生的,不用我方做)
  - 我方系统主动推送给用户的通知(下载已签发 / 申请已通过 / 资源到期)用机器人发卡片

## 10. 风险与坑

| 风险 | 缓解 |
| --- | --- |
| 事件重试 4 次会重投同一事件 | webhook **必须幂等**;按 `instance_code + event_type + status` 做去重 |
| `tenant_access_token` 多实例并发刷新 | 中心化 Redis 缓存 + 分布式锁(见 §5.2 伪代码) |
| 审批模板更新后,字段 control id 可能变 | 模板更新走"版本化":新模板新 `approval_code`,旧实例仍用旧 code 查询 |
| 文件附件接口走 v2 路径(不是 v4) | 在 API 客户端封装里显式区分;别假设全路径都在 `/v4` |
| 网页授权 scope 不足导致拿不到 `open_id` | 申请 `contact:user.base:readonly` 最小集 |
| 事件 3 秒响应窗口 | webhook 入队后立即返回 200,重业务异步;长流程用 Celery |
| 大规模通讯录同步频率限制 | 走"每日全量 + 事件增量",不要短周期轮询 |
| SDK 高层未覆盖审批 | 直接用 `client.request()` 通用调用,把审批 API 当 REST 用 |

## 11. 与企业微信对比(简短,不再深入)

| 维度 | 飞书 | 企业微信 |
| --- | --- | --- |
| 官方 Python SDK | `lark-oapi`,活跃 | 多为第三方维护 |
| API 文档导航 | 文档站结构清晰,审批 v4 单独成块 | 散在不同入口 |
| 事件 vs 回调区分 | 明确两套 | 混用,需要看具体接口 |
| 鉴权 token | `tenant_access_token`(2h) | `access_token`(2h,语义类似) |
| 加解密 | EncryptKey + VerificationToken | EncodingAESKey + Token |
| 审批模板代码化 | API + 后台 devMode | API 较弱,后台为主 |

这条与用户初步结论"飞书更适合第三方开发者对接"一致;基础在于:文档结构 + 官方 SDK + API 一致性。

## 12. 与方案 v2 的差异

| v2 方案 | 本调研 v0.1 |
| --- | --- |
| 钉钉 / 企微 二选一 | **飞书**,企微已排除 |
| 临时权限申请通过"钉钉/企微"做 | 临时权限申请走飞书审批 v4 → IT 在 LDAP/AD(待定身份源)加入临时组 |
| "案例库下载需审批,触发邮件/企微通知" | 改:走飞书审批 v4 + 飞书机器人/IM 推通知(邮件可保留作备份) |

## 13. 实测发现

> **测试上下文:** 2026-05-15,应用 `cli_aa8c58fae5391be7`,域名 `rusheslab.taoxiplan.com`(测试服 `47.109.30.236`)。bridge PoC = FastAPI + Caddy(自动 ACME),代码见 [`feishu-integration/`](../../../feishu-integration/),复跑脚本 [`feishu-integration/scripts/create_approval.py`](../../../feishu-integration/scripts/create_approval.py)。
>
> 本节记录"已实测"的事实,**与 §1–12 调研推论分开**,以便后续接手者机械地核 caveat。

### 13.1 接口路径修正

| 操作 | 实测路径 | 备注 |
| --- | --- | --- |
| 创建审批定义 | `POST /open-apis/approval/v4/approvals` (**复数**) | §4 表格里写的单数 `/approval` **404 page not found**;请按这里更新认知 |
| 创建审批实例 | `POST /open-apis/approval/v4/instances` | 与 §4 一致 ✓ |
| 查询审批实例 | `GET  /open-apis/approval/v4/instances/{instance_code}` | 与 §4 一致 ✓ |
| 拿 tenant_access_token | `POST /open-apis/auth/v3/tenant_access_token/internal` | §5 一致 ✓ |

### 13.2 创建审批定义最简 payload(可复制)

```json
{
  "approval_name": "@i18n@approval_name",
  "description":   "@i18n@desc_text",
  "viewers":       [{"viewer_type": "TENANT"}],
  "form":          {"form_content": "[{\"id\":\"reason\",\"type\":\"textarea\",\"name\":\"@i18n@reason_label\",\"required\":true}]"},
  "node_list": [
    {"id": "START"},
    {"id": "node_approver", "name": "@i18n@approver_label", "node_type": "OR", "approver": [{"type": "Free"}]},
    {"id": "END"}
  ],
  "i18n_resources": [{"locale": "zh-CN", "is_default": true, "texts": [
    {"key": "@i18n@approval_name",   "value": "rushes-lab PoC 测试审批"},
    {"key": "@i18n@desc_text",       "value": "PoC 端到端测试模板"},
    {"key": "@i18n@reason_label",    "value": "申请理由"},
    {"key": "@i18n@approver_label",  "value": "审批人"}
  ]}],
  "process_manager_ids": []
}
```

关键约束(踩坑后总结):

- `node_list` **必须含 `{"id":"START"}` 和 `{"id":"END"}` 边界节点**,且 START/END 不需要 `name` / `node_type` / `approver`。缺失则飞书返回 `1390001 node amount not enough`。
- `form` 是 `{"form_content": "<widgets JSON 压缩转义后的字符串>"}`,**不是**直接的 widget 数组。
- `approval_name` / `description` 必须以 `@i18n@` 开头,且**总长 ≥ 9 字符**(`@i18n@` 占 6 字符,后接的 key 名 ≥ 3 字符)。
- `process_manager_ids: []` 空数组可被接受,**不强制必须指定模板管理员**(与官方 Java sample 一致)。
- `viewers` 至少一项;`viewer_type: TENANT` 全企业可见最简。
- `approver[].type = "Free"` 表示发起人自选审批人,创建实例时通过 `node_approver_open_id_list` 指定具体审批人,避免模板里硬编码 user_id。

实测结果:`POST /approvals` 200 OK,返回 `approval_code` + `approval_id`。

> **API 化 vs UI 配置的权衡:** §4 推荐"初期 UI 配置,迭代后代码化"。本次测试证明 API 路径**可用**,但 **不**意味着"推荐 API 化"作为长期路径 —— 控件类型 / 节点 / 审批人类型尚未系统性测过,UI 配置仍是模板演化期更稳的选项。

### 13.3 创建审批实例 + 状态查询

`POST /open-apis/approval/v4/instances` payload:

```json
{
  "approval_code": "<from §13.2>",
  "user_id":  "ou_xxxx",
  "open_id":  "ou_xxxx",
  "form":     "[{\"id\":\"reason\",\"type\":\"textarea\",\"value\":\"申请理由具体文本\"}]",
  "node_approver_open_id_list": [
    {"key": "node_approver", "value": ["ou_xxxx"]}
  ]
}
```

- `form` 在创建实例时同样是 **JSON 字符串**(不是对象);value 字段填用户输入。
- `node_approver_open_id_list[].key` 必须与模板 `node_list` 中业务节点的 `id` 严格一致(本例 `node_approver`)。
- 实测响应 200,`status: PENDING`,飞书 App 立即收到审批通知。

### 13.4 状态枚举(已实测 vs 未确认)

| 飞书 status | 实测 | 触发动作 |
| --- | --- | --- |
| `PENDING` | ✓ | 创建实例后初始态 |
| `APPROVED` | ✓ | 审批人在飞书 App 点"同意"后 ≤ 数秒内 `GET /instances/:id` 即可观察到 |
| `REJECTED` | ✗ 未实测 | 走拒绝流程时验证 |
| `CANCELED` | ✗ 未实测 | 申请人撤销时验证 |
| `DELETED` / `HIDDEN` | ✗ 未实测 | 管理员后台操作时验证 |

`timeline[].type` 已观察到 `START` / `PASS`;其他枚举值(可能含 `REJECT`、`CANCEL` 等)**未实测**。

### 13.5 open_id 跨应用域的现象

测试期间出现:**给 `POST /instances` 传入 open_id `ou_075fa520...`(从其他应用的 API 调试台复制),飞书在响应里返回的 open_id 是 `ou_0d8a04338cd3...`,不同字符串**,但实例正确创建、用户正确收到通知。

可观察事实:`open_id` 是 **应用作用域** 标识;一份用户标识在不同应用下值不同。**具体机制(union_id 反查 / user_id 检索 / 其他)未确认**,但现象说明:

- bridge 收到来自上游(material-storage)的 open_id 时,**必须假定是 bridge 这个飞书应用域下的 open_id**,不能是其他应用域的
- 这条直接影响契约 MS-FB-002(身份解析):上游传给 bridge 的标识应当是 bridge 应用域下的 open_id,或者上游传内部 user_id / email,由 bridge 内部解析为本应用 open_id

### 13.6 事件订阅 webhook 路径(未实测)

本次测试只走通了 url_verification 握手(明文 payload),**未触发任何真实加密事件**。原因:测试应用的事件订阅在飞书后台未配置具体事件类型 + 未发布版本(应用创建人非测试者,需走 owner 审批,本次跳过)。

后续待验证项见 §13.7。

## 13.7 待办(实测层)

按"机械可核"形式列出,做完即勾掉,把对应 caveat 从本文档 / ADR-0001 移除:

- [ ] 在事件订阅页**抄回**实际可勾选的审批相关事件名清单(v1 `approval_instance` 还是 v2 `approval.approval.instance.{approved,rejected,canceled}_v4`;影响 ADR-0001 §3 子决策的实测落地)
- [ ] 真实加密事件(有 `encrypt` 字段的 outer body)走完一次 callback,验证 `ENCRYPT_KEY` 解密路径
- [ ] 拒绝流程实测:确认 `status = "REJECTED"` 与 timeline 新增 type 枚举值
- [ ] 撤销流程实测:`POST /instances/cancel` + 确认 `status = "CANCELED"` 与 timeline 新增 type 枚举值

## 13.8 待办(策略 / 决策层)

- [ ] 在飞书开发者后台创建自建应用(由测试者本人创建,避免 owner 协作 friction),拿 `app_id` / `app_secret` / `verification_token` / `encrypt_key`(用户操作)
- [ ] 通过 §13.2 payload 或 UI 配置 2 个生产模板:
  - 资源下载审批
  - 临时权限申请
  并把 `approval_code` 提交到方案
- [ ] 验证 `tenant_access_token` 刷新 + Redis 缓存代码在我方栈下的可行性
- [ ] **决策依赖:** 用户身份源(Q2)决定后,通讯录同步策略才能定;若选"飞书通讯录直接作 SoT",此处大幅简化
- [ ] 决策依赖:文件管理系统(Q1)PoC 决定 C' / B 路线后,审批触发点的接入位置才能定(NC 跳转 vs 全自研 Web)

## 14. 参考文档

| 标题 | URL | 抓取日期 |
| --- | --- | --- |
| 飞书审批 v4 概述 | <https://open.feishu.cn/document/server-docs/approval-v4/approval-overview?lang=zh-CN> | 2026-05-15 |
| 三方审批实例同步 | <https://open.feishu.cn/document/ukTMukTMukTM/uczM3UjL3MzN14yNzcTN?lang=zh-CN> | 2026-05-15 |
| Get custom app tenant_access_token | <https://open.feishu.cn/document/server-docs/authentication-management/access-token/tenant_access_token_internal> | 2026-05-15 |
| oapi-sdk-python README | <https://github.com/larksuite/oapi-sdk-python/blob/main/README.zh.md> | 2026-05-15 |
| 事件概述 | <https://feishu.apifox.cn/doc-1940218> | 2026-05-15 |
| 回调概述 | <https://feishu.apifox.cn/doc-7518464> | 2026-05-15 |
| 获取 user_access_token | <https://open.feishu.cn/document/authentication-management/access-token/get-user-access-token?lang=zh-CN> | 2026-05-15 |
