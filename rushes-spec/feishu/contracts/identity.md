# Contract: 身份解析 (identity) v1

## 能力描述

`feishu-integration`(下称 **bridge**)向上游消费者(目前为 `material-storage`)暴露的"用户身份解析 + 状态变更推送"REST + webhook 契约。bridge 内部用飞书通讯录作 SoT(material-storage [ADR-0002](../../material-storage/decisions/0002-feishu-contacts-as-identity-source.md)),通过事件订阅 + 每日全量对账维护本地缓存;**本契约对上游屏蔽**飞书 `tenant_access_token` 管理、`open_id` 跨应用域差异、字段 scope 复杂性。

**覆盖需求:** [`../requirements/from-material-storage.md`](../requirements/from-material-storage.md) **MS-FB-002**(P0)。

**不覆盖:** MS-FB-001(已 [`approval.md v1`](./approval.md)) / 003 / 004 / 005 / 006 —— 各自独立契约。

**调研依据:** [`../research/contacts-as-identity-source.md`](../research/contacts-as-identity-source.md)(全字段实测 + 离职闭环分析 + scope 差异)

## 版本

- **当前版本:** v1
- **状态:** draft
- **变更日志:**
  - 2026-05-15: initial draft (feishu agent)

## 通用约定

### Base path

同 [`approval.md`](./approval.md):本契约所有路径以 `/v1` 为前缀。下文 `POST /users/...` 等省略 `/v1` 前缀。

### 认证

同 `approval.md`:上游每次调用 bridge **必须** 携带 header `X-Bridge-Token: <token>`,失败返 `401 unauthorized`。

### Content-Type

`application/json; charset=utf-8`。

### 时间表示

ISO 8601 UTC 字符串。

### 错误响应通用结构

```json
{
  "code": "<machine-readable string code>",
  "message": "<human-readable description>",
  "details": { /* 可选,具体错误特有字段 */ }
}
```

### 标识符约定

- **`open_id`** —— 飞书应用作用域,**本契约的主键**。所有 GET / batch 接口都以此为唯一查询标识。**material-storage 内部用什么字段做 PK 与本契约无关**(其 ADR-0002 §"字段策略"用 `internal_user_id`),但**与 bridge 对接时一律带 open_id**
- **`union_id`** —— 飞书 ISV 作用域(同一开发者的多应用稳定),作 OIDC `sub` 用(见 [`../decisions/0002-bridge-as-oidc-provider.md`](../decisions/0002-bridge-as-oidc-provider.md));本契约里以**只读字段**返回给上游备份,**不用作查询参数 / 主键**。若 material-storage 在内部只存了 union_id 想查用户,**应自维护本地 `union_id → open_id` 反查表**(SSO 流程能填),或等 v1.x 加 `GET /users/by-union-id/{union_id}` endpoint
- **`user_id`** —— 飞书企业内部短 id,**本契约不暴露**(回收行为飞书侧不明确,见调研 §2.3)
- **`open_department_id`** —— 飞书部门作用域稳定 id;本契约 `department_chain[]` 使用此字段

## 数据模型

### User 对象(所有 GET / lookup 响应共用)

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `open_id` | string | ✓ | 主键 |
| `union_id` | string | ✓ | ISV 作用域稳定 id;**bridge 必返**,作上游备份 |
| `name` | string | ✓ | 用户姓名 |
| `en_name` | string \| null | — | 英文名;租户内未维护时为 `null` |
| `email` | string \| null | — | 见下 §"字段 null 语义" |
| `enterprise_email` | string \| null | — | 同上 |
| `employee_no` | string \| null | — | 工号;租户未维护时 `null` |
| `employee_type` | integer | ✓ | 飞书 `employee_type` 枚举(1=正式,2+=自定义);具体语义由飞书租户管理后台定义 |
| `gender` | integer \| null | — | 0=未知 1=男 2=女(飞书规范) |
| `city` / `country` / `work_station` / `job_title` | string \| null | — | 个人信息字段;租户未维护时 `null` |
| `is_tenant_manager` | bool | ✓ | 飞书企业管理员标记 |
| `join_time` | string (ISO 8601 UTC) | ✓ | 入职时间。bridge 把飞书 unix epoch 秒转换成 ISO 字符串 |
| `department_chain` | array of `DeptRef`(见下) | ✓ | 用户所属部门链;至少一项;**有且仅有一项** `is_primary: true` |
| `manager_open_id` | string \| null | — | **直接主管的 `open_id`**;无主管(如老板)时 `null`。给 MS-FB-005 审批人路由用 |
| `job_level_id` | string \| null | — | 飞书职级 id;无则 `null` |
| `status` | `UserStatus` 对象(见下) | ✓ | 状态机,**整体必填,子字段亦必填** |
| `is_external` | bool | ✓ | **bridge 暴露的所有 user 此字段恒为 `false`**;`true` 的查询不由 bridge 服务(走 material-storage 自管,见 [`../research/contacts-as-identity-source.md`](../research/contacts-as-identity-source.md) §4)。预留字段为日后 material-storage 想用统一 schema 表示两类账号时,bridge 端语义不歧义 |
| `last_synced_at` | string (ISO 8601 UTC) | ✓ | bridge 本地缓存对该用户**最近一次同步**(事件投递或全量对账)的时刻 |

#### `DeptRef` 子对象

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `open_department_id` | string | ✓ | 飞书部门稳定 id |
| `name` | string | ✓ | 部门名 |
| `is_primary` | bool | ✓ | 主部门 |

#### `UserStatus` 子对象

| 字段 | 类型 | 必填 | 默认值约定 | 说明 |
| --- | --- | --- | --- | --- |
| `is_resigned` | bool | ✓ | `false` | 已离职。**关键安全字段** |
| `is_frozen` | bool | ✓ | `false` | 被冻结(IT 暂停服务) |
| `is_unjoin` | bool | ✓ | `false` | 已邀请但尚未注册 / 加入企业 |
| `is_activated` | bool | ✓ | `true` | 首次登录后置 `true`;v1 上游一般可忽略 |
| `is_exited` | bool | ✓ | `false` | 用户主动退出企业 |

> bridge 必返 `status` 对象;若飞书侧 GET 在边界场景下未返回某子字段,bridge **以默认值填充**,绝不向上游返回 `null`。**这是 v1 SLA**。

### 字段 null 语义

`email` / `enterprise_email` 在飞书 `tenant_access_token` 下默认为空字符串([`../research/contacts-as-identity-source.md`](../research/contacts-as-identity-source.md) §5)。bridge 处理规则:

- 飞书 GET 返回**空字符串** → bridge **转换为 `null`**(避免上游 `if v == ""` 与 `if v is None` 双重判断)
- bridge 通过 OAuth 流程([MS-FB-004 SSO 契约,待起草])拿到该用户的 `user_access_token`,从 `/authen/v1/user_info` 拉到的 `email` 落 bridge 缓存后,**`email` 字段填充为真实值**
- 用户尚未走过 OAuth、且 IT 后台未全局开放应用读取邮箱字段时,`email` 长期为 `null`,**上游须容忍**

> **v1 不实现:** 主动触发"为某用户填充 email"的 API(等同于让管理员代用户走 OAuth,飞书侧无此能力)。

### v1 不暴露的字段(显式列出,免猜)

- `mobile` / `mobile_visible`:material-storage [ADR-0002 §"mobile/email 策略"](../../material-storage/decisions/0002-feishu-contacts-as-identity-source.md) 明示"暂不取,目前无短信通知场景"。本契约 v1 字段集合**不返**这两个字段。**若 material-storage 未来需要,v1.x 演进加上**(向后兼容,新增 response 字段允许)
- 飞书 `user_id`(企业内部短 id):回收行为飞书侧不明确,见 [SoT 调研 §2.3](../research/contacts-as-identity-source.md);本契约**永不**暴露
- `avatar_*` 头像 URL:暴露策略待 MS-FB-003 消息卡片推送契约一并讨论,v1 不返
- `custom_attrs`:见 §"未决问题" #2

## Endpoints

### GET `/users/{open_id}` — 单用户查询

**用途:** 上游(material-storage)以 `open_id` 查询用户信息。**99% 调用走此接口**。bridge 优先读本地缓存;缓存 miss 时回源飞书 `GET /contact/v3/users/:user_id`,落库后返回。

**Path 参数:**

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `open_id` | string | ✓ | 飞书 `ou_*` 开头的 32 位标识 |

**Query 参数:** 无

**Response 200:**

返回 §"User 对象" 全字段。

**Errors:**

| HTTP | `code` | 含义 | 客户端建议 |
| --- | --- | --- | --- |
| 400 | `invalid_open_id` | `open_id` 不是合法的飞书 ou_* 格式 | 修请求 |
| 401 | `unauthorized` | bridge token 校验失败 | 检查 env |
| 404 | `user_not_found` | bridge 本地缓存 miss 且飞书侧也返回不存在 | 上游应清理本地该 user 的引用 |
| 404 | `not_in_scope` | `open_id` 存在但不在本飞书应用 scope 内(飞书应用可见范围限制) | 不应该出现于已 SSO 登录过的用户;IT 需扩 scope |
| 503 | `feishu_upstream_unavailable` | bridge 缓存 miss 且飞书 API 不可达 | 退避重试;bridge 内部已有指数退避 |
| 500 | `internal_error` | bridge 故障 | 重试 + 告警 |

---

### POST `/users/batch_get_by_open_ids` — 批量查询

**用途:** 上游一次拿多个用户;典型场景是审批人列表批量解析或操作日志渲染。

**Request body:**

```json
{
  "open_ids": ["ou_xxxx", "ou_yyyy", ...]
}
```

| 字段 | 类型 | 必填 | 限制 |
| --- | --- | --- | --- |
| `open_ids` | array of string | ✓ | 1 ≤ len ≤ 100;超出返回 `400 too_many_open_ids` |

**Response 200:**

```json
{
  "users":      [/* User 对象数组,可能 < len(open_ids) */],
  "not_found":  ["ou_xxxx", ...]   // 这批中查不到的 open_ids
}
```

**Errors:**

| HTTP | `code` | 含义 |
| --- | --- | --- |
| 400 | `invalid_request` | body 不是合法 JSON / `open_ids` 缺失或类型错 |
| 400 | `too_many_open_ids` | > 100 |
| 401 | `unauthorized` | — |
| 503 | `feishu_upstream_unavailable` | bridge 缓存 miss 且回源飞书时整批失败 |
| 500 | `internal_error` | — |

**部分成功语义:** bridge 优先全部命中本地缓存,缓存 miss 的部分回源飞书。若飞书侧批量调用部分用户失败,bridge **仍返回 200 + 成功部分写入 `users`,失败部分写入 `not_found`**(等同于 404 行为);**不**因部分失败把整体改 503。`feishu_upstream_unavailable` 仅当**全部回源失败**才返。

---

### 关于反查(email / mobile → open_id)

**v1 不暴露**反查 endpoint。理由:

- material-storage [ADR-0002](../../material-storage/decisions/0002-feishu-contacts-as-identity-source.md) 明示身份获取主路径是 **SSO + JIT provisioning**,SSO 流程在 bridge 内部就完成了 email→open_id 映射,上游本来就持有 open_id 上下文
- 反查 endpoint 会引入 mobile E.164 归一化、scope 边界处理、邮箱大小写敏感等一堆边界 case,v1 不值得为"<1% 场景"承担
- 若 material-storage 后续真有"无 open_id 上下文的反查"需求(例如审计日志旧 email 反查),v1.x 演进加 `POST /users/lookup` endpoint,**新增 endpoint 是向后兼容的**

---

## bridge → upstream Webhook(用户状态变更推送)

### 推送时机

bridge 收到飞书通讯录事件后,异步推送 **`user.status_changed`** 事件给上游 webhook。**仅在以下情形触发**(其他字段变化只更新 bridge 内部缓存,不推上游,避免噪音):

| 飞书事件 | 触发 webhook `change_type` |
| --- | --- |
| `contact.user.deleted_v3` | `resigned` |
| `contact.user.updated_v3`(`status.is_frozen` 翻转) | `frozen` / `unfrozen` |
| `contact.user.updated_v3`(**白名单字段变化**:`name` / `department_chain` / `manager_open_id` / `job_level_id`) | `metadata_changed` |
| `contact.user.created_v3` | `created` |

**白名单之外的字段变化(头像 / city / `email` 后填充 / `mobile_visible` 等)不触发 webhook**;上游若需要它们,主动调 `GET /users/{open_id}` 拉,或等下一个白名单变化的 webhook 顺带刷。

> 设计说明:bridge 把飞书多个细分事件统一为单一 `user.status_changed`(类似 `approval.status_changed` 模式),屏蔽飞书 schema 演进。白名单收紧是为避免"IT 给某人改头像"也推上游;若未来发现白名单不够,**加新字段是 v1.x 演进**(向后兼容,新增 change_type 或扩 metadata 白名单)。

### 接收端配置

部署侧配置(同 [`approval.md`](./approval.md)),不在请求里:

- `target_url`:上游接收 URL
- `signing_secret`:HMAC 共享密钥

### Request(bridge → upstream)

`POST <target_url>`

**Headers**(与 `approval.md` webhook 一致):

| Header | 说明 |
| --- | --- |
| `Content-Type` | `application/json; charset=utf-8` |
| `X-Bridge-Event-Id` | bridge 生成 UUIDv4;上游按此去重 |
| `X-Bridge-Timestamp` | Unix epoch 秒(字符串) |
| `X-Bridge-Signature` | `"sha256=" + hex(HMAC_SHA256(signing_secret, timestamp + "." + raw_body))`,其中 `raw_body` 是 **transport 层原始字节**,**不是**上游 SDK 反序列化后重 dumps(同 `approval.md` 同名 header 措辞) |

**Body schema:**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `event_id` | string | 同 `X-Bridge-Event-Id` |
| `event_type` | 固定 `"user.status_changed"` | v1 唯一事件类型 |
| `occurred_at` | string (ISO 8601 UTC) | 状态变更时刻 |
| `change_type` | enum (`created` / `resigned` / `frozen` / `unfrozen` / `metadata_changed`) | 见上"推送时机"表 |
| `user` | §"User 对象" 完整快照 | **变更后**的当前状态 |
| `previous_user` | §"User 对象" 或 `null` | **变更前**快照;`created` 时为 `null`;其他 `change_type` 基于 `contact.user.deleted_v3.old_object` 等飞书事件附带字段填充 |
| `changed_fields` | array of string | **白名单内**实际发生变化的字段名列表(只在 `change_type=metadata_changed` 时有意义,可能取值:`name` / `department_chain` / `manager_open_id` / `job_level_id`);其他 `change_type` 时返回**空数组**。上游可直接读此字段判断"改了什么",无须 diff `user` vs `previous_user` |

**Body 示例(离职事件):**

```json
{
  "event_id": "a0c91b22-7e2d-4a3c-9c0a-d12f5a8bc671",
  "event_type": "user.status_changed",
  "occurred_at": "2026-05-15T13:34:56Z",
  "change_type": "resigned",
  "changed_fields": [],
  "user":          { "open_id": "ou_...", "name": "张三", "status": { "is_resigned": true,  "is_frozen": false, ... }, /* ... */ },
  "previous_user": { "open_id": "ou_...", "name": "张三", "status": { "is_resigned": false, "is_frozen": false, ... }, /* ... */ }
}
```

### 上游响应约定 / bridge 侧重试 / 重放保护

**完全沿用 [`approval.md`](./approval.md) §"bridge → upstream Webhook" 同名小节** ——
- 3 秒内 2xx 即 ACK
- 5 次指数退避(15s → 60min cap)
- `event_id` 跨重试不变
- `|now - timestamp| ≤ 300s` 重放保护

具体不再重复;实施时若两个契约的 webhook 行为分歧,**以本契约为准并在 PR 中讨论**。

### 幂等性(上游侧职责)

上游按 `X-Bridge-Event-Id` 去重。同 `approval.md`。

---

## 缓存语义(实施层 SLA,上游应了解但**不依赖底层细节**)

bridge 维护本地用户缓存,**不**做"对上游全透明的强一致"承诺:

- **事件路径:** 飞书事件 → bridge ≤ 数秒落缓存 → webhook 推上游
- **全量对账:** 每日凌晨(具体时间由部署侧配置)bridge 跑一次 `find_by_department(0)` + 子部门遍历,与本地缓存 diff,发现不一致写告警并修正缓存
- **`last_synced_at` 字段:** 每条 user 返回的此字段表示 bridge 缓存的同步时刻;上游可据此判断"这条数据陈旧度"
- **离职闭环 SLA:** webhook 投递成功后 ≤ 1 分钟内,上游应触发"撤销活跃 session + signed URL + 标记审批 invalid"等操作;webhook 重试失败的兜底由全量对账保证最迟 24 小时内一致

**关键提醒(给 material-storage):** 安全关键决策(例如"该用户能下载此资源吗")**不应**单纯依赖单次 GET 的 `status.is_resigned`;应**消费 webhook + 本地状态机**。GET 仅作"信息渲染"用途。

## 向后兼容承诺(v1 → 未来)

| 变更类型 | v1 → v1.x(允许) | v1 → v2(必要) |
| --- | --- | --- |
| 新增**可选** request 字段 | ✓ | — |
| 新增 response 字段(含 User 子对象新增字段) | ✓ | — |
| 新增 webhook `change_type` 枚举值 | ✓(上游应忽略未知值) | — |
| 新增 `UserStatus` 子字段(默认值 `false`) | ✓ | — |
| 修改字段类型 / 改 path / 改 `change_type` 现有值语义 | ✗ | ✓ |
| 改 webhook 签名算法 / header 名 | ✗ | ✓ |
| `is_external` 字段语义("bridge 暴露的恒为 false")变更 | ✗ | ✓ |

破坏向后兼容**禁止**直接改 v1;必须新开 `## v2` 节,v1/v2 共存至少一个发版周期。

## 未决问题(留给后续 PR / Issue 跟踪)

1. **离职用户 `GET /contact/v3/users/:id` 飞书侧行为未实测**([SoT 调研 §9 待办 #1](../research/contacts-as-identity-source.md#137-待办实测层) + issue #17 P0)。若实测发现飞书侧返 404,**本契约 `GET /users/:open_id` 仍承诺 200**(从 bridge 缓存返,带 `status.is_resigned=true`)—— 这是**bridge 主动遮蔽**飞书 SchemaChange,不需要修契约
2. **`custom_attrs`(自定义字段)透传**:v1 不暴露;若 material-storage 未来需要,加 `custom_attrs: {<key>: <value>}` 可选字段,走 v1.x 演进
3. **职级 / 序列 / 角色字段**:v1 仅 `job_level_id` / `job_title`;若 MS-FB-005 审批人路由用到 `functional_role` / `job_family`,加字段或单开 routing 契约,v1.x 演进
4. **Webhook 多上游订阅**:目前假设单一上游(material-storage)。多 target_url + per-subscriber `signing_secret` 是 v2 才需要的改动
5. **写操作**:v1 **不暴露** 创建用户 / 改部门等写接口;飞书原本就少有自建应用写通讯录的合理场景;若日后需要单开 admin 契约

## 与 ADR-0002 的关系

本契约描述**bridge → 上游**的身份解析面;[`../decisions/0002-bridge-as-oidc-provider.md`](../decisions/0002-bridge-as-oidc-provider.md) 描述**bridge → 文件管理底座(NC/oCIS)**的 OIDC 身份面。

- bridge 内部用**同一份缓存**支撑两个对外面:OIDC `/oidc/userinfo` 的 claims 来自缓存;本契约的 `GET /users/:open_id` 响应也来自缓存
- 字段命名:本契约 `email` / `name` / `department_chain` 与 ADR-0002 OIDC claims (`email` / `name` / `groups`) **不强制同名**,但语义对应明确;OIDC `sub` = `union_id`(ADR-0002 决策),本契约也用 `open_id` 主键 + `union_id` 返回字段 —— **不矛盾,是同一份数据的两种暴露面**
