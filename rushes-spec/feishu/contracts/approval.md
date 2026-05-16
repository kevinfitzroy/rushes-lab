# Contract: 审批申请 (approval) v1

## 能力描述

`feishu-integration`(下称 **bridge**)向其上游消费者(目前为 `material-storage`)暴露的"审批申请 / 状态查询 / 撤销 + 状态变更推送"REST + webhook 契约。**bridge 内部通过飞书原生审批 v4 实现**,本契约的字段语义对上游屏蔽飞书的事件分散性、token 管理与 open_id 解析细节。

**覆盖需求:** [`../requirements/from-material-storage.md`](../requirements/from-material-storage.md) **MS-FB-001**(P0)。

**不覆盖** MS-FB-002 / 003 / 004 / 005 / 006 —— 它们各自由独立契约描述(待起草)。

## 版本

- **当前版本:** v1.1
- **状态:** draft
- **变更日志:**
  - 2026-05-15: v1 initial draft (feishu agent)
  - 2026-05-16: v1.1 — webhook body 加 `metadata` 可选字段(POST 时传入的 metadata 由 bridge 在 webhook 中原样回传);驱动:[MS-FB-007 v2](./approval-callback.md) 需要 `metadata.material_storage_ref` 关联本地资源。**向后兼容**(新增可选 response 字段允许)

## 通用约定

### Base path

bridge 暴露的所有 REST endpoint 都以 `/v1` 为前缀,具体监听端口与 host 由部署侧决定。本契约中所有 path 都省略该前缀,例:`POST /approvals` 实指 `POST /v1/approvals`。

### 认证(上游 → bridge,即 material-storage 调用 bridge)

- 上游每次调用 bridge **必须** 携带 header `X-Bridge-Token: <token>`。token 由部署侧在 env 注入(bridge 与上游各持一份,内部网络互信)。
- bridge 校验失败返回 `401 unauthorized`。
- 后续版本可能换成 mTLS 或 OAuth client credentials;v1 用共享 token 是工作区内部最低成本的方案。

### Content-Type

所有 POST/PATCH 请求 `Content-Type: application/json; charset=utf-8`,响应同。

### 时间表示

所有时间字段统一 **ISO 8601 UTC 字符串**(例 `"2026-05-15T12:34:56Z"`)。bridge 在内部把飞书的 Unix epoch 秒转换。

### 错误响应通用结构

非 2xx 响应一律是:

```json
{
  "code": "<machine-readable string code>",
  "message": "<human-readable description>",
  "details": { /* 可选,具体错误特有字段 */ }
}
```

各 endpoint 的 `code` 枚举在该 endpoint 节列出。

### 标识符

| 字段 | 含义 | 谁生成 |
| --- | --- | --- |
| `approval_id` | bridge 内部审批 id | bridge(UUIDv4 字符串,32-36 字符) |
| `feishu_instance_code` | 飞书侧 `instance_code` | 飞书,透传 |
| `applicant_open_id` | 申请人飞书 `open_id` | 飞书(由上游通过 MS-FB-002 解析后传入) |

## Endpoints

### POST `/approvals` — 发起审批申请

**用途:** 上游(material-storage)以"某用户对某资源/路径"为由发起一次审批。bridge 把上下文翻译成飞书审批表单字段,调用飞书 `POST /open-apis/approval/v4/instances`,落库后返回。

**Headers:**

| Header | 必填 | 说明 |
| --- | --- | --- |
| `X-Bridge-Token` | ✓ | 见"通用约定 → 认证" |
| `Idempotency-Key` | 推荐 | UUID 字符串;24 小时内同 key 返回同 `approval_id`,即使原请求成功也不重复创建;`Idempotency-Key` 不同但其他参数完全相同时**仍创建新实例**(上游有责任保证 key 唯一) |

**Request body:**

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `applicant_open_id` | string | ✓ | 申请人飞书 `open_id`。上游应先通过 MS-FB-002 解析。 |
| `approval_type` | enum (`resource_download` \| `temp_permission`) | ✓ | 审批类型,决定 `resource_ref` / `target_path` 的必填分支与飞书侧映射的 `approval_code` |
| `resource_ref` | string | 条件 | `approval_type=resource_download` 时必填:资源唯一标识(由上游约定语义,bridge 透传) |
| `target_path` | string | 条件 | `approval_type=temp_permission` 时必填:目标目录/路径 |
| `reason` | string | ✓ | 申请理由,1 ≤ len ≤ 500 字符 |
| `metadata` | object | 否 | 透传到飞书审批表单的键值对。**约定字段:** `valid_until`(ISO 8601 UTC,临时权限场景过期时间),`category`(资源类别字符串);其他键值会作为辅助文本展示,**bridge 不解释**。 |

**Request 示例:**

```json
{
  "applicant_open_id": "ou_a3935e60b01fd60679ce671cee771c6b",
  "approval_type": "resource_download",
  "resource_ref": "case-lib/2025/q4/clip-019.mp4",
  "reason": "客户案例汇报需要原片素材",
  "metadata": {
    "category": "case_library",
    "valid_until": "2026-05-22T23:59:59Z"
  }
}
```

**Response 200:**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `approval_id` | string | bridge 内部 id,后续 GET / POST withdraw / webhook 都以此为索引 |
| `feishu_instance_code` | string | 飞书 `instance_code`,留作上游侧 debug / 跨系统追踪 |
| `status` | enum (`pending`) | 初始状态固定 `pending` |
| `created_at` | string (ISO 8601 UTC) | bridge 落库时刻 |

**Errors:**

| HTTP | `code` | 含义 | 客户端建议 |
| --- | --- | --- | --- |
| 400 | `invalid_request` | JSON 缺字段 / 类型不符 / `reason` 超长 | 修请求 |
| 400 | `invalid_approval_type` | `approval_type` 不在枚举,或与必填分支不匹配(例如 `resource_download` 没带 `resource_ref`) | 修请求 |
| 401 | `unauthorized` | bridge token 校验失败 | 检查 env 配置 |
| 404 | `invalid_applicant` | `applicant_open_id` 在飞书侧不存在 | 重新走 MS-FB-002 解析 |
| 410 | `applicant_resigned` | open_id 对应用户已离职 | 上游侧友好提示 |
| 409 | `idempotency_conflict` | 同 `Idempotency-Key` 上次请求 body 与本次不一致 | 换 key 或对齐 body |
| 503 | `feishu_upstream_unavailable` | 飞书 API 5xx / 超时 / 限频(bridge 内部重试已经耗尽) | 退避后重试,bridge 内部已含指数退避 |
| 500 | `internal_error` | bridge 自身故障(DB / token 刷新失败 / 序列化等) | 重试 + 告警 |

---

### GET `/approvals/{approval_id}` — 查询单条状态

**用途:** 拉一次最新状态。常规流程下,上游应消费 webhook 而非轮询;此接口主要给上游 UI 的"立即刷新"按钮 / 对账脚本用。

**Path 参数:**

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `approval_id` | string | ✓ | bridge 内部 id |

**Response 200:**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `approval_id` | string | — |
| `feishu_instance_code` | string | — |
| `applicant_open_id` | string | — |
| `approval_type` | enum | 同 POST 入参 |
| `status` | enum (见 §"状态机") | 当前状态 |
| `previous_status` | enum \| null | 上一状态;**初始 `pending` 时为 `null`** |
| `decided_by` | string \| null | 终态决策者的 `open_id`;非终态为 `null` |
| `decided_at` | string (ISO 8601 UTC) \| null | 进入当前状态的时间;`pending` 状态为 `null`,其他状态必有 |
| `comment` | string \| null | 决策者备注(飞书侧填的);可能为空字符串或 `null` |
| `created_at` | string (ISO 8601 UTC) | 落库时刻 |
| `metadata` | object | 与 POST 入参一致,透传 |

**Errors:**

| HTTP | `code` | 含义 |
| --- | --- | --- |
| 401 | `unauthorized` | — |
| 404 | `approval_not_found` | `approval_id` 不存在 |
| 500 | `internal_error` | — |

---

### POST `/approvals/{approval_id}/withdraw` — 申请人主动撤销

**用途:** 申请人在状态进入终态前撤销审批。bridge 调飞书 `POST /open-apis/approval/v4/instances/cancel`,并同步状态。

**Path 参数:** 同 GET。

**Request body:**

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `actor_open_id` | string | ✓ | 发起撤销的用户 `open_id`;bridge 校验必须等于该审批的 `applicant_open_id`,否则 `403 forbidden_actor` |
| `reason` | string | 否 | 撤销理由,≤ 200 字符;bridge 透传到飞书 cancel 接口 |

**Response 200:**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `approval_id` | string | — |
| `status` | enum (`withdrawn`) | 撤销后状态 |
| `decided_at` | string (ISO 8601 UTC) | 撤销时间 |

**Errors:**

| HTTP | `code` | 含义 | 客户端建议 |
| --- | --- | --- | --- |
| 401 | `unauthorized` | — | — |
| 403 | `forbidden_actor` | `actor_open_id` ≠ `applicant_open_id` | 不允许第三方撤销 |
| 404 | `approval_not_found` | — | — |
| 409 | `cannot_withdraw_terminal_state` | 当前状态已是 `approved` / `rejected` / `withdrawn`,不可撤销 | 上游 UI 应隐藏撤销按钮 |
| 503 | `feishu_upstream_unavailable` | — | — |
| 500 | `internal_error` | — | — |

> 状态变更后,**bridge 仍会按"状态变更 webhook"约定推一条 `current_status=withdrawn` 给上游**(同 webhook 通道,保证上游只听一条流即可)。

---

## 状态机

```
pending ─┬─→ approved   (审批人通过)
         ├─→ rejected   (任一审批人拒绝)
         └─→ withdrawn  (申请人撤销 / 飞书 CANCELED 事件)
```

- **终态:** `approved` / `rejected` / `withdrawn`;终态不允许任何状态变更。
- **v1 不实现的状态:**
  - `expired`:飞书原生无"过期"事件。若 material-storage 需要"申请 N 天未决自动失效",**v1 内需自管**(根据 `metadata.valid_until` 在上游侧定时扫描);后续版本评估是否由 bridge 提供 TTL 调度。
  - `deleted` / `archived`:飞书审批被管理员删除/隐藏的状态;**v1 内忽略**,bridge 不向上游推此变更。后续版本评估。
- **GET `/approvals/{approval_id}` 在飞书侧 DELETED 之后的行为:** 返回 bridge 落库的**最后已知状态**,bridge 不感知后续在飞书侧发生的删除/隐藏。这意味着上游若需要"已被删除"的可观测性,要走告警 / 对账,不能仅靠本接口。

bridge ↔ 飞书状态映射(实施侧参考,不属于契约稳定面):

| 飞书 instance status | bridge `status` |
| --- | --- |
| `PENDING` | `pending` |
| `APPROVED` | `approved` |
| `REJECTED` | `rejected` |
| `CANCELED` | `withdrawn` |
| `DELETED` / `HIDDEN` | 忽略,不推 webhook |

---

## bridge → upstream Webhook(状态变更推送)

### 推送时机

bridge 收到飞书审批实例的状态变更事件(`approval.approval.instance.{approved,rejected,canceled}_v4` 等)并完成内部状态落库后,**异步**向上游已配置的 webhook URL 推送一条 `approval.status_changed`。

> 设计说明:bridge 把飞书侧的多个细分事件(approved/rejected/canceled)统一为单一 `approval.status_changed`,屏蔽飞书的事件分散性。上游只需注册一条 webhook 处理逻辑。

### 接收端配置(由 bridge 部署侧配置,不在请求里)

- `target_url`:上游接收 URL
- `signing_secret`:HMAC 共享密钥(env 注入)

### Request(bridge → upstream)

`POST <target_url>`

**Headers:**

| Header | 说明 |
| --- | --- |
| `Content-Type` | `application/json; charset=utf-8` |
| `X-Bridge-Event-Id` | bridge 生成的事件唯一 id(UUIDv4),用于上游幂等去重 |
| `X-Bridge-Timestamp` | 事件发出时刻的 Unix epoch 秒(字符串) |
| `X-Bridge-Signature` | `"sha256=" + hex(HMAC_SHA256(signing_secret, timestamp + "." + raw_body))`,其中 `timestamp` 取 `X-Bridge-Timestamp` 头值,`raw_body` 是 **transport 层接收到的原始字节序列**,**不是**上游 SDK 反序列化后再重新 `json.dumps` 出的字符串(键序、空格、Unicode escape 任一差异都会让 HMAC 校验失败)。上游务必从 ASGI / WSGI 框架的 raw body API 读取(FastAPI:`await request.body()`;Flask:`request.get_data(cache=True, as_text=False)`)再做 HMAC。 |

**Body schema:**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `event_id` | string | 同 `X-Bridge-Event-Id`,放 body 内方便日志检索 |
| `event_type` | string,固定 `"approval.status_changed"` | v1 唯一事件类型,后续新增事件不破坏向后兼容 |
| `occurred_at` | string (ISO 8601 UTC) | 状态变更发生时刻(取自飞书事件的决策时间;若飞书无则等于 bridge 落库时刻) |
| `approval_id` | string | bridge 内部 id |
| `feishu_instance_code` | string | 透传 |
| `previous_status` | enum | 状态机定义的非终态。**v1 内取值固定为 `pending`**(`pending` 是 v1 唯一非终态);保留为 enum 字段是为了向前兼容,后续若新增中间态(例如多级审批的 `pending_level_2`),不破坏 schema。 |
| `current_status` | enum (`approved` \| `rejected` \| `withdrawn`) | 终态 |
| `decided_by` | string | 决策者 `open_id`(`withdrawn` 时为 `applicant_open_id`) |
| `comment` | string \| null | 决策者备注;可能为空 |
| `metadata` | object | **v1.1 新增**:POST 时上游传入的 `metadata` 由 bridge 原样回传。**bridge 不解析、不修改、不补字段**。例如 MS-FB-007 v2 场景下含 `material_storage_ref` 等业务 ID,详见 [`approval-callback.md`](./approval-callback.md)。**v1 客户端不读此字段时行为不变**(向后兼容,新增可选 response 字段允许) |

**Body 示例:**

```json
{
  "event_id": "5f2a3b1e-9c7d-4e0a-b8f1-32a1bd6c1234",
  "event_type": "approval.status_changed",
  "occurred_at": "2026-05-15T12:34:56Z",
  "approval_id": "a0c91b22-7e2d-4a3c-9c0a-d12f5a8bc671",
  "feishu_instance_code": "81D31358-93AF-92D6-7425-01A5D67C4E71",
  "previous_status": "pending",
  "current_status": "approved",
  "decided_by": "ou_c8f4afe4ab51ce0a1c6711d6c0e2f3a9",
  "comment": "已核对客户合同范围",
  "metadata": {
    "valid_until": "2026-05-22T23:59:59Z",
    "category": "case_library"
  }
}
```

### 上游响应约定

- **3 秒内**返回 HTTP `2xx`(任何 2xx 都算 ACK)。
- 返回非 2xx / 超时 / 网络错误,bridge 触发重试。
- 上游响应 body 由 bridge 忽略。

### bridge 侧重试

- 重试次数: **最多 5 次**(含首次)。
- 重试间隔: **指数退避**,初始 15 秒,倍增,上限 60 分钟。
- 重试期间 `X-Bridge-Event-Id` 不变(同一个事件 id),`X-Bridge-Timestamp` 与签名重新生成。
- 全部失败后 bridge 写告警日志,不再重试;上游可在事后调 GET `/approvals/{approval_id}` 对账。

### 幂等性(上游侧职责)

- 上游 **必须** 按 `X-Bridge-Event-Id` 去重。重试期内同一 event 会被重投。
- 上游也可加一道"`(approval_id, current_status)` 已处理过则忽略"的兜底,但 `event_id` 是 v1 契约的 SLA 字段。

### 重放保护

- 上游收到 webhook 应校验 `|now - X-Bridge-Timestamp| ≤ 300 秒`,超出窗口直接返回 `200`(不让 bridge 重试)但内部告警。

---

## 向后兼容承诺(v1 → 未来)

| 变更类型 | v1 → v1.x(允许) | v1 → v2(必要) |
| --- | --- | --- |
| 新增**可选** request 字段 | ✓ | — |
| 新增 response 字段 | ✓ | — |
| 新增 webhook `event_type`(例如 `approval.comment_added`) | ✓ | — |
| 新增状态枚举值(例如 `expired`) | ✗ —— 现有上游处理不到新值会漏 | ✓ |
| 删除字段 / 改字段类型 / 改 path | ✗ | ✓ |
| 改 webhook 签名算法 / header 名 | ✗ | ✓ |

破坏向后兼容的变更**禁止**直接改 v1 —— 必须新开 `## v2` 节,允许 v1 / v2 共存至少 1 个发版周期。

---

## 未决问题(留给后续 PR / Issue 跟踪)

1. **`expired` 状态的实现侧**(bridge TTL vs 上游自管):待 material-storage 实施开始后确认实际诉求。
2. **请求侧 `Idempotency-Key` 的 TTL**:目前定 24 小时,可能不够长(若上游侧 outbox / 重试任务跑超过 24h)。等实施后看实测调整。
3. **webhook 推送多上游订阅**:目前假设单一上游(material-storage)。若日后有其他项目订阅,需要扩展为多 target_url + per-subscriber `signing_secret`,这是 v2 才需要的改动。
