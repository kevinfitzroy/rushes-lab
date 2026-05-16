# Contract: IM 消息推送 (messaging) v1

## 能力描述

`feishu-integration`(下称 **bridge**)向上游(material-storage 等)暴露的 "**调 bridge 发飞书 IM 消息**" REST 契约。本质是 bridge 对飞书 [发送消息 API](https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/im-v1/message/create) 的瘦封装,加上 bridge 内部的:

- `tenant_access_token` 自动管理(上游免维护)
- recipient `open_id` 与 MS-FB-002 身份缓存的复用(校验在职 / 离职 fallback)
- 错误码语义化(把飞书 99991xxx 系列翻译成 bridge 标准错误)
- 限频缓冲(per-app 限额内的简单 token bucket,不替代 material-storage 主动节流)

**覆盖需求:** [issue #36](https://github.com/kevinfitzroy/rushes-lab/issues/36) — material-storage [ADR-0005](https://github.com/kevinfitzroy/rushes-lab/pull/33) §11.2 Gap 13 / §11.3。

**主用例:** 审批通过 / 拒绝后,material-storage 业务 UI 通知中心(主路径)+ 飞书 IM 卡片(增强路径,本契约)同步推给申请人,见 MS-FB-007 [`approval-callback.md`](./approval-callback.md) §5.

**不覆盖:**
- 飞书 IM 卡片**模板内容设计**(template_id 由 material-storage 在飞书开发者后台配置,本契约只负责"按 template_id 推消息")
- 卡片交互回调(`card_action_trigger` 等用户点击事件)— v1 范围内卡片是单向通知,无回调
- 群组消息(`chat_id`) / 邮箱接收(`email`)/ user_id / union_id — v1 仅支持 `open_id` 接收者
- 富文本(post) / 图片 / 文件 / 视频 / 音频 — v1 仅支持 `text` 和 `interactive (card)` 两种消息类型
- 批量发送 / 撤回 / 编辑 — v1 不实现,见 §"v1 不实现"
- 应用机器人能力开通 / 通讯录可见范围管理 — 由 IT 在飞书开发者后台 + 管理后台配,本契约假定就绪

**调研依据:**
- 飞书 IM v1 [发送消息 API zod schema](https://github.com/larksuite/lark-openapi-mcp/blob/main/src/mcp-tool/tools/zh/gen-tools/zod/im_v1.ts)
- 飞书消息卡片官方文档(SPA,通过 lark-openapi-mcp + SDK 间接 verify)
- [`identity.md`](./identity.md) (MS-FB-002):recipient 身份与离职 fallback
- [`approval-callback.md`](./approval-callback.md) (MS-FB-007) §5:典型主用例

## 版本

- **当前版本:** v1
- **状态:** draft
- **变更日志:**
  - 2026-05-16: initial draft (feishu agent)

## 通用约定

### Base path

同其他 bridge 契约,所有 endpoint 以 `/v1` 为前缀(例:`POST /messages` 实指 `POST /v1/messages`)。

### 认证

上游每次调用必须携带 `X-Bridge-Token: <token>` header(同 [`approval.md`](./approval.md) 约定)。失败 `401 unauthorized`。

### Content-Type

`application/json; charset=utf-8`。

### 时间表示

ISO 8601 UTC。

### 错误响应

```json
{
  "code": "<machine code>",
  "message": "<human description>",
  "details": { /* 可选 */ }
}
```

### 标识符

- `recipient_open_id`:飞书 `open_id`(本应用域)。上游必须先通过 MS-FB-002 或 SSO session 拿到此 ID 再调本契约
- `feishu_message_id`:bridge 在本契约 response 里返,即飞书 `message_id`(`om_xxx`),供上游 audit 关联

## Endpoints

### POST `/messages` — 发送单条消息

**用途:** 调 bridge 向单个用户(`open_id`)推送一条飞书 IM 消息。bridge:
1. 校验 recipient(MS-FB-002 缓存,确认非 resigned / unjoin)
2. 取最新 `tenant_access_token`(bridge 内部缓存,自动刷新)
3. 把上游传入的 `message_type` / `content` 翻译成飞书 `msg_type` / `content`(JSON 字符串)
4. 调飞书 `POST /open-apis/im/v1/messages?receive_id_type=open_id`
5. 返回 `feishu_message_id` + `sent_at`

**Headers:**

| Header | 必填 | 说明 |
| --- | --- | --- |
| `X-Bridge-Token` | ✓ | — |
| `Idempotency-Key` | 推荐 | UUID 字符串,**长度 ≤ 50 字符**,字符集限 UTF-8 alphanumeric + `-_`(飞书 `uuid` 字段限制);bridge 翻译成飞书 `uuid` 字段 dedup(飞书 server 端 1 小时内重复 `uuid` 返同 message_id);**违反长度 / 字符集返 `400 invalid_request`**(防止飞书侧 `uuid` 校验失败抛 503 误导上游);不传则 bridge 自动生成 |

**Request body:**

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `recipient_open_id` | string | ✓ | 飞书 `ou_*` 32 位标识 |
| `message_type` | enum (`text` / `card_raw` / `card_template`) | ✓ | 见下三种分支 |
| `content` | object | ✓ | 内容字段集合,**形状取决于 `message_type`**,见 §"message_type 分支" |

**Response 200:**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `feishu_message_id` | string | 飞书返的 `om_*` 消息 id;上游可用作 audit 关联 |
| `sent_at` | string (ISO 8601 UTC) | bridge 落库的发送成功时刻 |

**Errors:**

| HTTP | `code` | 含义 | 客户端建议 |
| --- | --- | --- | --- |
| 400 | `invalid_request` | body 缺字段 / 类型错 / `message_type` 不在枚举 | 修请求 |
| 400 | `invalid_content` | `content` 字段与 `message_type` 不匹配(例如 text 类型 content 没有 `text` 字段)| 修请求,见 §"message_type 分支" |
| 401 | `unauthorized` | bridge token 校验失败 | 检查 env |
| 404 | `recipient_not_found` | `recipient_open_id` 在 MS-FB-002 缓存与飞书都查不到 | 上游清理本地引用 |
| 410 | `recipient_resigned` | open_id 对应用户已离职 — bridge 用 MS-FB-002 缓存做**乐观校验**;缓存命中 is_resigned=true 直接返 410。**注意:** MS-FB-002 缓存有数秒 ~ 1 min 延迟([见 MS-FB-002 §"缓存语义"](./identity.md));缓存未感知到离职但飞书已拒收时,bridge 仍按飞书侧错误码翻译,**410 不保证绝对一致,是 best-effort** | 通知申请人由其他通道处理(邮件兜底) |
| 403 | `recipient_not_in_scope` | recipient 不在应用可见范围内(飞书 99991xxx 系列) | IT 在飞书后台扩 scope |
| 413 | `content_too_large` | text > 150 KB,card > 30 KB(飞书限制) | 缩内容 / 拆多条 |
| 422 | `invalid_card_template` | `template_id` 飞书后台不存在 / 已删除 / `template_variable` 字段集合与模板不匹配。**注:** 422 是 client error 语义,但**运维误删模板**也走此码;material-storage 监控应区分(per template_id 失败率突增 = 运维 vs 单次错 = caller)| 上游侧 verify template 后再调 / 监控触发告警 |
| 429 | `rate_limited` | bridge 缓冲队列已满 / 飞书 per-app 限频触发 | 退避后重试(建议指数退避 1s/5s/15s 上限 60s)|
| 503 | `feishu_upstream_unavailable` | 飞书 API 5xx / 超时(bridge 内部已重试) | 退避 |
| 500 | `internal_error` | bridge 故障 | 重试 + 告警 |

---

## message_type 分支

### `message_type = "text"` — 纯文本

**`content` schema:**

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `text` | string | ✓ | UTF-8 文本,`1 ≤ len ≤ 150 KB`(飞书限制);支持飞书 `<at user_id="ou_xxx">@xxx</at>` 等 inline 标记 |

**Example:**

```json
{
  "recipient_open_id": "ou_a3935e60b01fd60679ce671cee771c6b",
  "message_type": "text",
  "content": { "text": "你的下载申请已通过,请前往 https://material-storage.internal/downloads 查看" }
}
```

bridge 内部翻译为飞书:

```json
{ "msg_type": "text", "content": "{\"text\":\"...\"}" }
```

(`content` 是 JSON 字符串,bridge 负责转义)

---

### `message_type = "card_raw"` — 原始卡片 JSON

**`content` schema:**

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `card` | object | ✓ | 飞书 [卡片 JSON 结构](https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/feishu-cards/card-json-v2-structure),上游构造并传入。bridge 不解析、直接 `JSON.stringify(card)` 后作为飞书 `content` 字段值 |

**约束:** `JSON.stringify(card)` **后的字节数** ≤ 30 KB(飞书限制按 stringified body 算,不是 object 内存大小或字符数);bridge 在 send 前 stringify 后计字节,违反返 `413 content_too_large`。

**Example:**

```json
{
  "recipient_open_id": "ou_xxxxxxxx",
  "message_type": "card_raw",
  "content": {
    "card": {
      "schema": "2.0",
      "config": { "wide_screen_mode": true },
      "header": { "title": { "tag": "plain_text", "content": "下载申请已通过" } },
      "elements": [
        { "tag": "div", "text": { "tag": "lark_md", "content": "**资源:** clip-019.mp4\n**审批人:** 王经理" } },
        { "tag": "action", "actions": [
            { "tag": "button", "text": { "tag": "plain_text", "content": "去下载" }, "url": "https://material-storage.internal/downloads/xxxx" }
        ]}
      ]
    }
  }
}
```

> **设计意图:** `card_raw` 是上游完全自管路径,适合 quick prototyping 或动态生成的卡片。生产场景**推荐 `card_template`**(下一节),把卡片设计与代码解耦。

---

### `message_type = "card_template"` — 卡片模板

**`content` schema:**

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `template_id` | string | ✓ | 飞书消息卡片模板 ID(`AAq*` 前缀),在飞书开发者后台 [搭建工具](https://open.feishu.cn/cardkit/) 创建模板后获得 |
| `template_version_name` | string | 否 | 模板版本号(语义化版本字符串,例 `"1.0.0"`);省略则飞书使用模板的"当前发布版本" |
| `template_variable` | object | 否 | 模板变量值字典(key = 模板里定义的变量名,value = 字符串 / 数字 / 数组等,具体由模板定义) |

bridge 内部翻译为飞书:

```json
{
  "msg_type": "interactive",
  "content": "{\"type\":\"template\",\"data\":{\"template_id\":\"AAqxxxxx\",\"template_version_name\":\"1.0.0\",\"template_variable\":{...}}}"
}
```

**Example(对应 MS-FB-007 审批通过场景):**

```json
{
  "recipient_open_id": "ou_a3935e60b01fd60679ce671cee771c6b",
  "message_type": "card_template",
  "content": {
    "template_id": "AAqkLzAbcDef1",
    "template_version_name": "1.0.0",
    "template_variable": {
      "requester_name": "张三",
      "resource_name": "case-lib/2025/q4/clip-019.mp4",
      "approver_name": "王经理",
      "decision_at": "2026-05-16 14:30",
      "deep_link": "https://material-storage.internal/downloads/by-approval/<approval_id>"
    }
  }
}
```

> `deep_link` 是 material-storage UI 入口 URL,**不含 token / presigned URL**;详见 §"与 MS-FB-007 协同 → 安全要求"。

> **设计意图:** template_id 在飞书开发者后台**集中管理**,改文案 / 改样式 / 加 i18n **不需要改代码**;bridge 端零知识,纯透传。

**模板 ID 验证:** bridge 不维护 template_id 白名单(那将与飞书后台不同步);若 template_id 飞书侧不存在,飞书 API 会返 99991xxx 类错误,bridge 翻译为 `422 invalid_card_template`。

---

## 与 MS-FB-007 `approval-callback.md` 的协同

典型审批结果通知流(详 MS-FB-007 §5):

```
飞书审批通过 → bridge webhook → material-storage handler
                                  │
                                  ├─→ 0. handler 按 MS-FB-001 §webhook 做
                                  │    HMAC-SHA256 校验 + X-Bridge-Event-Id dedup
                                  │    (信任 webhook 输入的前提)
                                  ├─→ 1. material-storage 签 MinIO presigned URL
                                  ├─→ 2. material-storage 写业务 UI 通知中心(主路径)
                                  └─→ 3. (本契约,增强路径)material-storage 调
                                         bridge POST /v1/messages
                                         { recipient_open_id, message_type=card_template,
                                           content: { template_id, template_variable:
                                             { ..., deep_link } } }
                                  → bridge 调飞书 IM API
                                  → 申请人在飞书收到卡片,点击 deep_link
                                  → 跳回 material-storage 业务 UI(deep_link 是 UI 入口 URL)
                                  → UI 端 OIDC session 鉴权 → 拉 MinIO presigned URL 下载
```

### 安全要求:`deep_link` 设计约束

⚠️ **必须:** `deep_link` 是 **material-storage 业务 UI 的入口 URL**,**不带任何 token / 一次性 nonce / presigned URL**。UI 端依靠 OIDC session(MS-FB-004)鉴权后再生成短 TTL 的 MinIO presigned URL。

**原因:** 飞书 IM 卡片里的 URL **会进入企业 IM 历史**,可被:
- 飞书搜索功能搜索
- 用户多设备同步
- 截屏 / 转发到其他渠道

IM 历史**不可清**(撤回消息也不能清接收方已下载的本地副本)。若 deep_link 里嵌了一次性 token,token 一旦泄漏到 IM 外部,bridge / material-storage 无法回收。这是 MS-FB-007 v1 §6.1 已经识别的同族风险(虽然 v2 改 MinIO 后**已经**通过"不在 IM 暴露 presigned URL"消除,但 deep_link 设计仍要符合同一原则)。

## 限频(rate limiting)

### 飞书 per-app 限额

飞书 IM 消息 API 有 per-app 限额(具体阈值 [按文档](https://open.feishu.cn/document/server-docs/im-v1/message/create) ~50 req/s,各产品环境略有差异);超出返 99991400 类错误码,bridge 翻译为 `429 rate_limited`。

### bridge 缓冲策略(v1)

bridge **不实现内部队列 / 主动限流** —— 把节流责任留给上游 material-storage。bridge 行为:

- 收到上游请求 → 立即调飞书 API
- 飞书返 429 → bridge **立即** 返 `429 rate_limited`(不重试)
- 上游负责退避 + 重试(推荐指数退避 1s / 5s / 15s 上限 60s)

**v1.x 评估:** bridge 加内部 token bucket(per-app)+ 队列吸收瞬时尖峰;暂时 v1 不做(material-storage 业务量级估计 ≤ 1 msg / 用户 / 分钟,远低于飞书限额)。

## 向后兼容承诺(v1 → 未来)

| 变更类型 | v1 → v1.x(允许) | v1 → v2(必要) |
| --- | --- | --- |
| 新增 `message_type` 枚举值(例如 `post` 富文本)| ✓ | — |
| 新增 response 字段(例如 `feishu_chat_id` 群上下文) | ✓ | — |
| 新增 batch endpoint `POST /messages/batch` | ✓ | — |
| 改 `recipient_open_id` 字段名 / 改为支持 `union_id` | ✗ | ✓ |
| 删除 `message_type` 枚举值(例如废 `card_raw`) | ✗ | ✓ |
| 改 `feishu_message_id` 含义(例如改为 bridge 自管 id)| ✗ | ✓ |

## v1 不实现 / 未决

| # | 项 | 备注 |
| --- | --- | --- |
| 1 | 批量发送 (`POST /messages/batch`) | v1.x 评估;飞书有 [批量消息 API](https://open.feishu.cn/document/server-docs/im-v1/batch_message/send) 可包装 |
| 2 | 撤回 / 编辑消息 | 用例稀少;material-storage 误发可走飞书 IM 客户端手动撤回 |
| 3 | 群组接收 (`chat_id`)| 当前业务场景全是 1-to-1 通知;群通知如有需求 v1.x 加 |
| 4 | 其他 `receive_id_type`(`email` / `user_id` / `union_id`)| 单一 `open_id` 路径简化;email/user_id 反查由 MS-FB-002 提供,上游先调 MS-FB-002 拿 open_id 再调本契约 |
| 5 | 其他 `msg_type`(post / image / file / audio / media / sticker / share_chat / share_user / system) | text + card 足够覆盖通知场景;其他类型按需 v1.x 加 |
| 6 | 卡片交互回调 (`card_action_trigger`) | 当前所有卡片是单向 URL 跳转;若日后需要 inline 操作(在卡片里直接 approve / reject),需新契约 MS-FB-? 处理 callback 流 |
| 7 | bridge 主动模板版本管理 | template_id + version 由飞书后台管理,bridge 不缓存 / 不验证 |
| 8 | bridge 内部 token bucket 限流 | 见 §"限频" v1.x 评估 |
| 9 | 富文本签名 / 加密 | 上游 → bridge 走 X-Bridge-Token + 内部网络;不引入应用层加密 |

## 与其他契约的关系

| 契约 | 关系 |
|---|---|
| [`identity.md`](./identity.md) (MS-FB-002) | recipient 校验通过其缓存;离职 fallback 路径依赖其 status 字段 |
| [`approval-callback.md`](./approval-callback.md) (MS-FB-007) | **主用例触发方**;material-storage 收到 approval webhook 后**同步**调本契约推 IM(增强通知)|
| [`approval.md`](./approval.md) (MS-FB-001) | 无直接耦合;审批申请走 MS-FB-001 REST,本契约用于"任意通知"(包括但不限于审批结果)|
| [`sso.md`](./sso.md) (MS-FB-004) | 无直接耦合;但 recipient_open_id 通常从 OIDC session `feishu_open_id` claim 取 |

## PoC 验收清单(bridge 实施 + material-storage 模板配置后)

1. [ ] material-storage 在飞书开发者后台搭建卡片模板,拿到 `template_id`
2. [ ] material-storage 调 `POST /v1/messages` with `message_type=text` 给自己(测试 recipient = 测试者 open_id),验证文本能收到
3. [ ] material-storage 调 `POST /v1/messages` with `message_type=card_template` + 上一步的 template_id + 简单 template_variable,验证飞书 IM 收到卡片
4. [ ] **MS-FB-007 协同**:模拟审批通过 webhook → material-storage handler → 调本契约推 card_template → 申请人飞书 App 收到完整卡片,点 "去下载" 按钮跳回 material-storage UI 完成下载
5. [ ] 错误路径:故意传不存在的 `template_id` → 飞书返错 → bridge 翻译为 `422 invalid_card_template`(确认错误码语义)
6. [ ] 离职 fallback:故意传一个 `is_resigned=true` 的 recipient_open_id → bridge 返 `410 recipient_resigned`(material-storage 走邮件兜底)
7. [ ] 限频:material-storage 1 秒内调本契约 ≥ 60 次 → 飞书 429 → bridge **立即** 返 `429 rate_limited`(v1 bridge **不**自动重试)→ material-storage 按指数退避**重新调用 bridge**;在飞书限频窗口结束后(秒级),material-storage 重试**最终成功**(成功归因 = material-storage 客户端重试,不是 bridge 自动)
