# Contract: 审批回调 (approval-callback) v2

## 能力描述

定义 `feishu-integration`(下称 **bridge**)在 **"审批通过后由上游自签资源访问凭据"** 场景下,**向上游(material-storage)单向推送 `approval.callback` webhook** 的契约。

**与 v1 的关键区别(supersedes 整个 v1):**

material-storage 在 ADR-0005([PR #33](https://github.com/kevinfitzroy/rushes-lab/pull/33))决议**去除 Seafile 中间层**,改用 MinIO + 自研业务 UI 三层架构。在新架构下:

| 维度 | **v1**(已弃,原文件名 `approval-seafile.md`)| **v2**(本契约) |
| --- | --- | --- |
| 资源签发方 | bridge 调 Seafile API 签 share-link | **material-storage** 自签 MinIO presigned URL(短 TTL)|
| bridge 是否知道资源细节 | 是(seafile_repo_id / seafile_path)| **否**(只透传 material-storage 内部 ref) |
| bridge 是否调下游存储 | 是(Seafile)| **否**(纯 webhook 通知) |
| 通知用户路径 | bridge 调飞书 IM 卡片 | material-storage 业务 UI 通知中心(主)+ MS-FB-008(增强,独立契约) |
| 状态机 | 含 `approved_link_failed` 异常态(因 bridge 调 Seafile 可能失败)| 简化:无该异常态,**bridge 只推 webhook** |
| 文件名 | `approval-seafile.md` | `approval-callback.md`(去 Seafile 标签) |

**覆盖需求:** [issue #35](https://github.com/kevinfitzroy/rushes-lab/issues/35)(blocking),material-storage [ADR-0005](https://github.com/kevinfitzroy/rushes-lab/pull/33) §11.1 "[读 — 敏感]" 段 + §11.2 Gap 4 + §11.3。

**不覆盖:**
- 审批申请发起 / 查询 / 撤销:[MS-FB-001 `approval.md`](./approval.md) v1
- 申请人身份解析:[MS-FB-002 `identity.md`](./identity.md) v1
- 飞书 IM 卡片推送:MS-FB-008(待起草,见 [issue #36](https://github.com/kevinfitzroy/rushes-lab/issues/36))
- material-storage 业务 UI / MinIO presigned URL 签发逻辑:material-storage 范围

## 版本

- **当前版本:** v2
- **状态:** draft
- **变更日志:**
  - 2026-05-15: ~~v1 (approval-seafile.md) initial draft~~
  - 2026-05-16: **v2** — ADR-0005 触发,整体重写;v1 supersede;文件重命名 `approval-seafile.md` → `approval-callback.md`(git mv 保 history)

## 1. 关系定位:与 MS-FB-001 webhook 的区别

**MS-FB-001 v1.1+**(本 PR 同步升级,见 §"对 MS-FB-001 的依赖")已有 `bridge → upstream` webhook(`event_type=approval.status_changed`),覆盖**所有飞书审批**的状态变更。

本契约(MS-FB-007 v2)**不是新的物理 webhook 端点**,而是:

1. **MS-FB-001 webhook 的 specialization**:针对"申请下载资源"这类审批 + material-storage 是消费者的场景,定义额外的 metadata 约定 + 上游消费流程 SLA
2. 物理上,material-storage 收到的是**同一 webhook URL + 同一 POST body**,event_type 仍是 `approval.status_changed`
3. 区分方式:**`metadata` 字段含 `material_storage_ref`** 即标识本审批属于本契约的 download 场景(material-storage 收到后按本契约 §5 流程处理)

> **设计动机:** 不开第二 webhook 端点,避免 bridge 同一事件双推、避免 material-storage 收两次。

## 2. 通用约定

### 认证 / 签名 / 重放保护 / 重试

**完全复用 [`approval.md` §"bridge → upstream Webhook"](./approval.md)** 的:
- `X-Bridge-Token` / `X-Bridge-Event-Id` / `X-Bridge-Timestamp` / `X-Bridge-Signature` headers
- HMAC-SHA256 签名约定(raw_body 是 transport 字节)
- 5 次指数退避(15s → 60min cap),`event_id` 跨重试不变
- 重放保护(`|now - timestamp| ≤ 300s`)
- 幂等性:上游按 `X-Bridge-Event-Id` 去重

不在本契约内复述;参 MS-FB-001。

### 标识符约定

- `approval_id` —— MS-FB-001 同款 bridge 内部 id
- `material_storage_ref` —— **material-storage 内部资源 ID**,POST `/v1/approvals` 时上游传入 `metadata.material_storage_ref`,bridge **完全透传**(不解析、不持久化业务语义、不暴露给飞书审批表单),webhook 回传

## 3. 上游(material-storage)POST `/v1/approvals` 约定

material-storage 走 [`approval.md` POST `/v1/approvals`](./approval.md) 发起申请时,**本契约要求**:

| 字段 | 约束 | 说明 |
| --- | --- | --- |
| `approval_type` | `resource_download` | 复用 MS-FB-001 已有枚举 |
| `applicant_open_id` | 飞书 `open_id` | MS-FB-001 标准 |
| `reason` | string ≤ 500 | MS-FB-001 标准 |
| `metadata.material_storage_ref` | **string,必填** | material-storage 内部资源 ID(其内部表 PK / UUID / 业务路径,语义由 material-storage 定);bridge 视为 opaque,**绝不**解析格式 |
| `metadata.*`(其他) | 可选 | 透传 |

> **bridge 不校验 `material_storage_ref` 的格式 / 存在性**(它是 material-storage 的内部 ID,bridge 无权也无法验证)。若 material-storage 给了错误的 ref,后续 webhook 回传相同的错值,material-storage 自身需在 webhook handler 里做"是否还存在 / 是否权限合法"二次校验。

## 4. bridge → upstream Webhook(本契约的核心)

### 推送时机

- material-storage 通过 POST `/v1/approvals` 提交,`metadata.material_storage_ref` 已填
- 飞书审批人在飞书 App 操作(通过 / 拒绝)
- 飞书事件 → bridge → bridge 通过 [`approval.md` webhook](./approval.md) 推送 material-storage

### Webhook body(MS-FB-001 v1.1 升级后的完整字段)

bridge → material-storage `POST <target_url>`,body:

| 字段 | 类型 | 必返 | 说明 |
| --- | --- | --- | --- |
| `event_id` | string | ✓ | 同 `X-Bridge-Event-Id`,上游幂等键 |
| `event_type` | string,固定 `"approval.status_changed"` | ✓ | MS-FB-001 v1 已定义 |
| `occurred_at` | string (ISO 8601 UTC) | ✓ | 状态变更时刻 |
| `approval_id` | string | ✓ | MS-FB-001 已定义 |
| `feishu_instance_code` | string | ✓ | MS-FB-001 已定义 |
| `previous_status` | enum (`pending`) | ✓ | MS-FB-001 已定义 |
| `current_status` | enum (`approved` / `rejected` / `withdrawn`) | ✓ | MS-FB-001 已定义 |
| `decided_by` | string | ✓ | 决策者 open_id |
| `comment` | string \| null | ✓ | 决策者备注 |
| `metadata` | object | ✓(v1.1 升级,**之前 v1 缺**)| **bridge 回传** POST 时的 `metadata` 对象原样;对本契约场景,**含 `material_storage_ref`**(material-storage 据此关联到本地资源) |

### Body 示例(approved)

```json
{
  "event_id": "a0c91b22-7e2d-4a3c-9c0a-d12f5a8bc671",
  "event_type": "approval.status_changed",
  "occurred_at": "2026-05-16T12:34:56Z",
  "approval_id": "f1e9a2b8-...",
  "feishu_instance_code": "81D31358-93AF-92D6-7425-01A5D67C4E71",
  "previous_status": "pending",
  "current_status": "approved",
  "decided_by": "ou_c8f4afe4ab51ce0a1c6711d6c0e2f3a9",
  "comment": "已核对客户合同范围",
  "metadata": {
    "material_storage_ref": "asset:case-lib/2025/q4/clip-019.mp4",
    "category": "case_library"
  }
}
```

## 5. 上游(material-storage)消费流程 SLA

material-storage 收到 `approval.status_changed` webhook 后,**判断 `metadata.material_storage_ref` 存在 → 进入本契约流程**;否则视为非 download 类审批(其他业务场景)。

**本契约要求 material-storage:**

1. 按 `X-Bridge-Event-Id` 幂等去重(MS-FB-001 §"幂等性" 已规定)
2. 校验 `metadata.material_storage_ref` 在本地仍存在 + 决策者 `decided_by` 仍合法授权(防 webhook 延迟导致状态漂移)
3. 按 `current_status` 分支:
   - **`approved`** → material-storage:
     - 签 **MinIO presigned URL**(material-storage [ADR-0005](https://github.com/kevinfitzroy/rushes-lab/pull/33) §11.1 [读 — 敏感] 段),TTL 由 material-storage 业务策略决定(推荐短 TTL ≤ 1h)
     - 落 audit(`audit:approval + signed_url + download`,见 PR #30 audit-schema)
     - 通知申请人(主路径:material-storage 业务 UI 通知中心;增强路径:MS-FB-008 飞书 IM 卡片,待该契约就绪)
   - **`rejected`** → material-storage:
     - 落 audit
     - 通知申请人(同上两路径)
   - **`withdrawn`** → material-storage:
     - 已有 presigned URL → 加入 revoke 黑名单(material-storage [ADR-0005](https://github.com/kevinfitzroy/rushes-lab/pull/33) Gap 1)
     - 落 audit
     - 通知申请人(可选)
4. 3 秒内返 HTTP 2xx ACK(MS-FB-001 SLA)

**bridge 不参与 §5 步骤 3 的任何动作**;bridge 唯一职责 = 推送 webhook + 重试。

## 6. 状态机

```
pending ─┬─→ approved   (审批人通过)
         ├─→ rejected   (审批人拒绝)
         └─→ withdrawn  (申请人撤销)
```

**完全继承 MS-FB-001 状态机**;**本契约 v2 不增加新状态**(v1 的 `approved_link_failed` 异常态在 v2 消失,因为 bridge 不再调下游存储,无失败可能)。

`expired` 状态由 material-storage 自管(其 presigned URL 自然过期),不属于 bridge 范畴。

## 7. 对 MS-FB-001 (approval.md) 的依赖:v1.1 升级

本契约依赖 **MS-FB-001 webhook body schema 含 `metadata` 字段**(`metadata` 在 v1 POST `/v1/approvals` 已定义,但 v1 webhook body **未**回传)。

**本 PR 同步升级 [`approval.md`](./approval.md) v1 → v1.1**:webhook body 加可选 `metadata` 字段,bridge 回传 POST 时 `metadata` 原样。

- 向后兼容(新增可选 response 字段允许,见 MS-FB-001 §"向后兼容承诺")
- 上游(material-storage)不读 `metadata` 字段时**行为不变**;读时按本契约 §3-§5 处理

## 8. v2 不实现 / 未决

| # | 项 | 说明 |
| --- | --- | --- |
| 1 | bridge 主动 IM 推送审批结果 | v2 完全不参与 IM 推送(v1 的 IM 卡片逻辑移除);走 MS-FB-008(待起草)由 material-storage 主动调 bridge → 飞书 IM API |
| 2 | bridge 主动调 material-storage REST API | 反向调用不存在;bridge 仅推 webhook |
| 3 | `expired` 状态 webhook 推送 | material-storage 自管 presigned URL 过期(本地状态机),bridge 无信号源 |
| 4 | 重试已失败的 webhook | MS-FB-001 已有 5 次指数退避;全失败后 material-storage 调 GET `/v1/approvals/:id` 对账,本契约不重复 |
| 5 | 多种 webhook URL(per `material_storage_ref` 路由) | v2 单一 URL(同 MS-FB-001);material-storage 内部按 `material_storage_ref` 分发 |

## 9. 向后兼容承诺(v2 → 未来)

| 变更类型 | v2 → v2.x(允许) | v2 → v3(必要) |
| --- | --- | --- |
| 新增 webhook 可选 metadata 字段约定(`material_storage_ref` 之外)| ✓ | — |
| 新增 status 枚举值(MS-FB-001 v2 加新 status)| ✗ | ✓(本契约 v3 跟进) |
| 改 `metadata.material_storage_ref` 语义(从 "material-storage 内部 ID" 改其他)| ✗ | ✓ |

## 10. v2 与 v1 的迁移路径

v1 已合并(PR #27),material-storage 实施未启动 → **无生产数据迁移代价**。v2 直接 supersede v1。git mv 保留文件 history。

## 11. 与其他契约的关系

| 契约 | 关系 |
| --- | --- |
| [`approval.md`](./approval.md) (MS-FB-001) | **本契约 v2 是 MS-FB-001 webhook 在 material-storage download 场景的 specialization + SLA**;同步升级 MS-FB-001 v1.1 加 metadata 回传 |
| [`identity.md`](./identity.md) (MS-FB-002) | material-storage webhook handler 按 `decided_by` open_id 解析决策者身份 |
| [`sso.md`](./sso.md) (MS-FB-004) | material-storage 作 OIDC RP 时通过本契约获得 `material_storage_ref` ↔ user open_id 关联 |
| ~~[`sso-seafile.md`](./sso-seafile.md) (MS-FB-006)~~ | 与 v2 不耦合;**MS-FB-006 同样作废**,见 [issue #34](https://github.com/kevinfitzroy/rushes-lab/issues/34) |
| MS-FB-008(待起草)| material-storage 收到本契约 webhook 后,可调 MS-FB-008 让 bridge 推飞书 IM 卡片;**不耦合**,二者由 material-storage 同步触发 |
| material-storage [ADR-0005](https://github.com/kevinfitzroy/rushes-lab/pull/33) | 本契约是 ADR-0005 §11.1 "[读 — 敏感]" 段 + §11.2 Gap 4 的精确版 |

## 12. PoC 验收清单(material-storage 实施启动 + MS-FB-001 v1.1 升级实施后)

1. [ ] material-storage 通过 [`approval.md` POST `/v1/approvals`](./approval.md) 提交,`metadata.material_storage_ref = "test:foo/bar.mp4"`
2. [ ] 飞书 App 收到审批,审批人通过
3. [ ] material-storage webhook handler 收到 POST,body 含 `metadata.material_storage_ref = "test:foo/bar.mp4"`(确认 bridge v1.1 metadata 回传工作)
4. [ ] material-storage 按 §5 流程签 MinIO presigned URL + 通知用户(此步实现在 material-storage 范围,本契约不验)
5. [ ] webhook 重试:故意 material-storage handler 返 500,bridge 5 次重试 + event_id 不变,material-storage 第二次按 event_id 去重不重复处理
6. [ ] 撤销流程:material-storage 调 [`approval.md` POST /v1/approvals/:id/withdraw`](./approval.md),webhook 推 `current_status=withdrawn` + 原 `metadata`
