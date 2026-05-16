# audit-schema.md — material-storage 审计日志 schema (v1)

> **版本:** v1 草案
> **日期:** 2026-05-16
> **驱动 issue:** [#16](https://github.com/kevinfitzroy/lab/issues/16) FastAPI 审计 SoT schema 设计
> **依据:**
> - storage-protocols-expert C 反馈(v0.3/v0.4 §6.2):敏感目录走 FastAPI 代理后,底座 activity 看不到,审计 SoT 必须归 FastAPI 自有
> - [ADR-0001](decisions/0001-no-full-custom-web-ui.md) §4(b) 敏感目录代理路径
> - [ADR-0002](decisions/0002-feishu-contacts-as-identity-source.md):`internal_user_id` PK + 飞书 `open_id`/`union_id` FK + 外部账号表
> - [ADR-0003](decisions/0003-seafile-only-poc.md):Seafile (Pro Edition) 单线;F-X
> - [v0.5 file-management-system.md](research/file-management-system.md) §3.2(主动转码代理版 / dataset B)+ §4
> - 飞书契约:[MS-FB-001](../feishu/contracts/approval.md) / [MS-FB-002](../feishu/contracts/identity.md) / [MS-FB-004](../feishu/contracts/sso.md) / [MS-FB-007](../feishu/contracts/approval-seafile.md)

## v0.5 re-anchor 说明

Issue #16 起草于 v0.3/v0.4(NC `oc_activity` 表 + oCIS event 流时代)。**v0.5 收敛后底座 = Seafile Pro 单线**,本文档相应:

- 移除与 NC `oc_activity` 对齐字段 —— NC 路线已退出(参见 v0.5 §11 归档 + ADR-0003)
- 与 **Seafile activity** (`/api/v2.1/activities/`) 对齐
- 显式吸收 [MS-FB-007 §7 share-link audit gap](../feishu/contracts/approval-seafile.md):Seafile activity log 看到的是 service account,不是真实 requester —— **这正是本文档存在的核心理由**

---

## 1. 设计前提(5 条 load-bearing)

### 1.1 Audit 必须 outlive user records

ADR-0002 允许账号 inactivate / 外部账号过期清理;审计 180 天保留。FK 单独不够 —— user 被清后,审计行的 `internal_user_id` 变孤儿,展示时无法回显谁是 actor。

**约束**:每条审计行**必须**存 user 快照列(`open_id_snapshot` / `name_snapshot` / `email_snapshot`),与 `internal_user_id` FK 并存;FK 在 user 被清后允许 `NULL`,但快照列保留。

### 1.2 Authoritativeness boundary

material-storage 不是所有事件的 SoT。**只对 material-storage 直接产生的事件(FastAPI 旁路 / 签名 URL / admin UI session / 旁路任务)是 SoT**;Seafile activity / bridge approval state 在它们自己的领域是 authoritative,material-storage 只存"observed projection"。

→ **§2 ownership matrix** 是本文档的组织原则,不是表清单。每个事件先归类:谁产生 / 谁权威 / material-storage 存什么。

### 1.3 Login event scope — Seafile login 不进 material-storage 审计

Seafile 自己 SSO 登录(Seafile 用户视角)由 **Seafile activity** + **bridge OIDC log** 共同记录;material-storage 不去 mirror,避免造假 SoT。

material-storage 自己的"登录日志"**只 cover material-storage admin UI session**(material-storage 自身作 OIDC RP 走 MS-FB-004 拿 sub=union_id,建立 admin session)。

### 1.4 Cross-system idempotency

bridge webhook 会重试,MinIO event 会重试。每条"webhook 驱动写入"必须有 UNIQUE `dedup_key`:

```
dedup_key = "<source>:<source_event_id>[:<status>]"
```

无 dedup,"approval status 变更" 日志重投后会双计,审计不可信。

### 1.5 Trace correlation across sidecar chain

一次用户上传触发 5-6 个事件:MinIO event → resolve Seafile commit → seafdav 下载 → ffmpeg 转码 → dataset B 写入 → AI 打标。**在 MinIO event 接收端铸造 `trace_id` (UUIDv4),透传整条链路**。

无 trace,审计退化为孤立事件;有 trace,可重建因果链,debug + 合规两用。

### 补充约束

- **审批 = state transition rows,不是 in-place UPDATE**:每次 webhook = 一行(`pending→approved` / `approved→expired` / etc.),匹配 MS-FB-001 / MS-FB-007 webhook 语义,允许完整历史重建
- **internal vs external user(ADR-0002)**:两个 nullable FK `internal_user_id` + `external_user_id`,DB CHECK 约束 `XOR`,不走 polymorphic 单列

---

## 2. Audit ownership matrix

| 事件类 | 产生方 | authoritative log | material-storage 存什么 |
| --- | --- | --- | --- |
| Seafile 用户登录 / 上传 / 浏览 / 直接下载(非敏感)| Seafile | Seafile `/api/v2.1/activities/` | **不存**(查询时跨 Seafile API) |
| bridge OIDC token 签发 / refresh / revoke | bridge | bridge 自有日志 | **不存** |
| material-storage admin UI session(material-storage 作 OIDC RP)| material-storage | material-storage 自己 | `admin_session_audit`(§4.5) |
| FastAPI 敏感目录下载代理(用户经 FastAPI 而非 Seafile share-link)| material-storage | material-storage 自己 | `download_audit kind=proxy`(§4.2) |
| FastAPI 签发临时签名 URL(外部账号场景)| material-storage | material-storage 自己 | `signed_url_audit`(§4.4) |
| 下载审批申请提交(MS-FB-007 POST)| material-storage 上游 | bridge MS-FB-007 GET 是 ground truth | `approval_audit`(§4.3,projection)|
| 下载审批状态变更(approved / rejected / etc.)| 飞书 → bridge → webhook | bridge MS-FB-007 GET | `approval_audit`(state transition row)|
| Seafile share-link 创建(approved 后 bridge 调 Seafile API)| bridge | Seafile activity 记 service account(audit gap),bridge MS-FB-007 GET 记真实 requester | `signed_url_audit`(§4.4,关联 `seafile_approval_id`)|
| 旁路任务(MinIO event 触发的缩略图 / AI / 转码)| material-storage 旁路 | material-storage 自己 | `sidecar_task_audit`(§4.6) |
| 数据集 dataset B 写入 | material-storage 旁路 | material-storage 自己 | `sidecar_task_audit` 含 `output_object` |
| 离职闭环(`contact.user.deleted_v3` → material-storage 撤销活跃 session / URL)| bridge → material-storage | material-storage 自己 | 三类 audit 行各记一笔 `revoked_due_to_resign` |

---

## 3. Cross-system event mapping(本文档存在的核心 — F-X / MS-FB-007 §7 audit gap)

material-storage 审计行 → Seafile activity / bridge log 的 **join key** 与 **gap 处理**:

| material-storage 事件 | 写入触发 | authoritative log 位置 | join key 进入 Seafile / bridge | gap 备注 |
| --- | --- | --- | --- | --- |
| `signed_url_audit`(share-link 创建)| MS-FB-007 webhook `approval.status_changed=approved` + 二次 GET confirm `share_link_url != null` | Seafile activity 记 `share_link.create by <SEAFILE_OPS_USERNAME>` | `share_link_token` + `seafile_repo_id` + `seafile_path` | **★ F-X / MS-FB-007 §7 audit gap:Seafile activity 视角的 actor = service account(非真实 requester)。真实 actor (`requester_open_id`) 只在 material-storage 本表 + bridge MS-FB-007 GET 可查。审计追溯必须从本表起,不能信 Seafile activity 的 actor 列。** 这一行是本文档存在的核心理由(Issue #16 expert-C 反馈) |
| `download_audit kind=proxy` | 用户经 FastAPI `/sensitive-download/<path>` GET | **无对应 Seafile activity 行**(FastAPI 直接走 seafdav 下载,Seafile 视角看到的是 service account 拉文件) | `seafile_repo_id` + `seafile_path` + `trace_id` | Seafile activity 拉文件的 actor = service account;FastAPI 自己的 audit 是真实 requester 唯一来源 |
| `download_audit kind=share_link_used` | 用户点 share-link 后 Seafile webhook 推送(若开)/ 或定时拉 Seafile activity 比对 | Seafile activity `file_download via share-link <token>` | `share_link_token` | Seafile activity 此处 actor 字段是匿名访客(share-link 默认无 user)→ material-storage 通过 `share_link_token` join 回 `signed_url_audit` 找到 issuer + 申请人 |
| `approval_audit`(状态变更行)| MS-FB-001 / MS-FB-007 webhook | bridge approval state DB | `approval_id` (MS-FB-001) + `seafile_approval_id` (MS-FB-007) | bridge 是 approval 主权,material-storage 是 projection;重投靠 `dedup_key` 收敛 |
| `admin_session_audit` | material-storage OIDC 登录回调 | bridge OIDC log | bridge `oidc_session_id`(若 bridge 暴露) | bridge **未必**暴露 session id;若不暴露则 join 不上,material-storage 端有完整记录够审计 |
| `sidecar_task_audit` | FastAPI 旁路 worker 启动 / 完成 | (无对应外部 log)| `trace_id` 关联 `download_audit` / `signed_url_audit` | material-storage 旁路是 closed loop,无外部 join 需求 |

---

## 4. 五类审计表 schema

> v1 = 字段表 + 类型 + 必填 + 含义,**不**写 DDL。具体 DDL 在 material-storage app skeleton 落地时定(选 Postgres / SQLite / etc. 由 deployment 决定)。

### 4.1 通用字段(每类表必含)

| 字段 | 类型 | 必填 | 含义 |
| --- | --- | --- | --- |
| `audit_id` | UUIDv4 | ✓ | PK,行内唯一 |
| `event_type` | enum string | ✓ | 该类表内子事件枚举(每类表 §4.x 单独定义) |
| `trace_id` | UUIDv4 \| null | — | 跨表关联(同一上传 / 同一下载的链式事件共 trace_id);MinIO event 接收端铸,sidecar / signed_url / download proxy 透传 |
| `dedup_key` | string | ✓ | 跨系统幂等;UNIQUE 索引;格式 `<source>:<source_event_id>[:<status>]`;**自产事件**用 `internal:<uuid>` 占位(不去重) |
| `internal_user_id` | FK \| null | — | ADR-0002 内部用户 PK;user 清理后 NULL |
| `external_user_id` | FK \| null | — | ADR-0002 外部账号 PK;DB CHECK:`(internal_user_id IS NOT NULL) XOR (external_user_id IS NOT NULL)` 或两者都 NULL(系统事件)|
| `open_id_snapshot` | string \| null | — | 写入时刻飞书 open_id;FK 清后唯一可读身份 |
| `union_id_snapshot` | string \| null | — | 同上,备份 |
| `name_snapshot` | string \| null | — | 写入时刻 user.name |
| `email_snapshot` | string \| null | — | 写入时刻 user.email(可 null 沿用 MS-FB-002 §"字段 null 语义") |
| `timestamp_utc` | ISO 8601 UTC | ✓ | 事件实际发生时刻(若是 webhook 驱动,取 webhook payload 内的事件时间,**不是** webhook 到达时间) |
| `inserted_at_utc` | ISO 8601 UTC | ✓ | 入库时间;审计完整性校对用 |
| `source_ip` | string \| null | — | 用户视角 IP(经 FastAPI / proxy header);system event NULL |
| `session_id` | string \| null | — | 用户 admin UI session,仅 admin UI 行为有值 |

### 4.2 `download_audit` — 下载日志

| 字段 | 类型 | 必填 | 含义 |
| --- | --- | --- | --- |
| (通用字段,§4.1)| — | — | — |
| `event_type` | enum | ✓ | `proxy_download` / `share_link_used` / `share_link_unused_expired` |
| `seafile_repo_id` | string | ✓ | — |
| `seafile_path` | string | ✓ | 文件路径,以 `/` 开头 |
| `download_kind` | enum | ✓ | `proxy`(FastAPI 代理,敏感目录)/ `share_link`(用户经 share-link 直下,可能匿名访客)|
| `share_link_token` | string \| null | — | `download_kind=share_link` 必填,关联 `signed_url_audit` 找 issuer |
| `bytes_transferred` | integer \| null | — | 实际下载完成字节;断流 / 失败 NULL |
| `http_status` | integer \| null | — | 200 / 206 / 416 / 5xx |
| `revoked_due_to_resign` | bool | ✓ | `false` | 离职闭环主动断流时置 `true`(关联 `internal_user_id` 此刻已 inactive) |

### 4.3 `approval_audit` — 申请日志(state transition rows)

每次状态变更 = 一行,**不**就地 UPDATE。

| 字段 | 类型 | 必填 | 含义 |
| --- | --- | --- | --- |
| (通用字段,§4.1)| — | — | — |
| `event_type` | enum | ✓ | `created` / `status_changed` / `withdrawn` / `expired` |
| `seafile_approval_id` | UUID | ✓ | MS-FB-007 内部 id |
| `approval_id` | string | ✓ | MS-FB-001 底层 approval id(同 PR #20 / PR #27 定义)|
| `previous_status` | enum \| null | — | 创建行 NULL;转移行 = 上一状态 |
| `current_status` | enum | ✓ | `pending` / `approved` / `approved_link_failed` / `rejected` / `withdrawn` / `expired`(沿用 MS-FB-007 §5 状态机)|
| `decided_by_open_id_snapshot` | string \| null | — | 状态由谁推动;申请人主动撤销 = requester open_id;系统过期 NULL |
| `comment_snapshot` | string \| null | — | 审批人备注(MS-FB-001 webhook payload) |
| `resource_ref` | string | ✓ | `<seafile_repo_id>:<seafile_path>`(写入时落 snapshot) |
| `dedup_key` 取值 | — | — | `feishu:<approval.message_id>:<current_status>`(MS-FB-001 webhook 字段);或 `internal:withdraw:<seafile_approval_id>:<actor_open_id>` 自产 |

### 4.4 `signed_url_audit` — 签名 URL 颁发日志

share-link 创建(approval 通过后)+ 外部账号一次性签名 URL 通用此表。

| 字段 | 类型 | 必填 | 含义 |
| --- | --- | --- | --- |
| (通用字段,§4.1)| — | — | — |
| `event_type` | enum | ✓ | `share_link_created` / `share_link_revoked` / `external_signed_url_issued` |
| `share_link_token` | string \| null | — | Seafile share-link token;`external_signed_url_issued` 自签时 NULL |
| `internal_signed_token` | string \| null | — | material-storage 自签 token(外部账号路径);Seafile share-link 时 NULL |
| `seafile_repo_id` | string | ✓ | — |
| `seafile_path` | string | ✓ | — |
| `issued_for_open_id_snapshot` | string \| null | — | 申请人(同 `open_id_snapshot`,但语义清晰所以重复出)|
| `expires_at_utc` | ISO 8601 UTC | ✓ | — |
| `password_protected` | bool | ✓ | `false` | 是否有密码(密码本身**不入此表**,见 MS-FB-007 §6.1)|
| `revoked_due_to_resign` | bool | ✓ | `false` | 同 §4.2 |
| `seafile_approval_id` | UUID \| null | — | 若由审批触发,关联 §4.3 |

### 4.5 `admin_session_audit` — material-storage admin UI session

> **scope:** material-storage 内部管理员 UI(material-storage 作 OIDC RP 走 MS-FB-004)。Seafile 自身的用户登录 **不** 入此表(参 §1.3)。

| 字段 | 类型 | 必填 | 含义 |
| --- | --- | --- | --- |
| (通用字段,§4.1)| — | — | — |
| `event_type` | enum | ✓ | `login` / `logout` / `session_revoked_due_to_resign` |
| `bridge_sub` | string | ✓ | OIDC `sub` claim(= 飞书 `union_id`) |
| `bridge_oidc_session_id` | string \| null | — | 若 bridge 暴露;**未必**有(MS-FB-004 v1 未约定 session id 暴露) |
| `user_agent_snapshot` | string \| null | — | UA 字符串截断 ≤ 256 字符 |
| `revoke_reason` | enum \| null | — | `manual_logout` / `idle_timeout` / `resign_event` / `admin_force` |

### 4.6 `sidecar_task_audit` — 旁路任务日志

MinIO event 触发后整条链上的每一步独立行,共享 `trace_id`。

| 字段 | 类型 | 必填 | 含义 |
| --- | --- | --- | --- |
| (通用字段,§4.1)| — | — | — |
| `event_type` | enum | ✓ | `minio_event_received` / `commit_resolved` / `seafdav_downloaded` / `ffmpeg_proxy_generated` / `dataset_b_written` / `ai_tag_generated` / `task_failed` |
| `task_kind` | enum | ✓ | `thumbnail` / `proxy_transcode` / `ai_tag` / `ai_embedding`(每个 trace_id 内一致) |
| `input_object` | string \| null | — | Seafile commit_id / MinIO object key / seafdav 下载路径(看步骤) |
| `output_object` | string \| null | — | dataset B 路径 / 缩略图路径(`task_failed` 则 NULL) |
| `status` | enum | ✓ | `started` / `succeeded` / `failed` / `retrying` |
| `error_class` | string \| null | — | `task_failed` 时填 exception class name(不入完整 stack,防日志膨胀;详细 trace 在 logger,本表是审计) |
| `duration_ms` | integer \| null | — | 该步骤耗时;`started` 行 NULL,`succeeded` / `failed` 行必填 |

---

## 5. 留存策略

| 类 | 最低保留 | 推荐保留 | 备注 |
| --- | --- | --- | --- |
| `approval_audit` | 180 天 | 730 天 | 合规审计核心 |
| `signed_url_audit` | 180 天 | 730 天 | 同上 |
| `download_audit` | 180 天 | 365 天 | 数据量最大;按 `download_kind` 可差异化(`proxy` 长留,`share_link_used` 360 天)|
| `admin_session_audit` | 180 天 | 365 天 | 内部操作可追溯 |
| `sidecar_task_audit` | 90 天 | 180 天 | 主要为 debug;失败行 (`status=failed`) 可单独长留 |

**deployment 提示:**

- 按月分区(Postgres native partitioning 或等价)便于过期数据 `DROP PARTITION`(快于 DELETE + VACUUM)
- 表本身 **insert-only**;不允许 UPDATE / DELETE 单行,只允许整分区 DROP(过期清理)+ 离职闭环时**新写撤销行**(不改原行)
- 备份策略:每日 logical backup → 异地存 ≥ 730 天(覆盖最长保留);RPO ≤ 24h

---

## 6. 导出/查询接口(admin-only,narrow scope)

按 [ADR-0001](decisions/0001-no-full-custom-web-ui.md)"不自研通用 Web UI",本节**显式 scope out user-facing 查询面板**。

| 接口 | 用途 | 形式 |
| --- | --- | --- |
| `GET /admin/audit/export?user=&from=&to=&type=&format=csv` | 按用户 / 时间 / 类型导出 | CSV(逐行 stream,大量数据不 OOM) |
| `GET /admin/audit/dedup-stats?from=&to=` | 重复 webhook 触发的 dedup 统计 | JSON,运维用 |

**v1 不实现:**

- 用户视角的"我看到我的下载历史"页面 → material-storage 业务 UI 范围,不是审计范围
- 实时审计 dashboard / SIEM 推送 → v1.x 评估
- 完整 export API spec(字段过滤 / multi-format)— 等 admin UI 落地后定

---

## 7. 与底座(Seafile activity)字段映射

| material-storage event | Seafile activity 对应行 | 字段对齐方式 |
| --- | --- | --- |
| `download_audit kind=share_link_used` | `op_type=file-download via share-link` | `share_link_token` 直接相等 |
| `signed_url_audit event_type=share_link_created` | `op_type=share-link-create by service account` | `share_link_token` + `repo_id` + `path` 三者相等;**actor 不对齐**(F-X / MS-FB-007 §7 audit gap)|
| `signed_url_audit event_type=share_link_revoked` | `op_type=share-link-delete by service account` | 同上 |
| `download_audit kind=proxy` | (无对应) | FastAPI 代理路径 Seafile 视角无 user activity(只有 service account 拉 seafdav)|
| `sidecar_task_audit` | (无对应) | 完全本地事件 |

**反向(从 Seafile activity 查 material-storage 关联):**

- Seafile activity 给 `share_link_token` → material-storage `signed_url_audit` JOIN → 拿真实 issuer 与 requester
- Seafile activity 给 `repo_id + path + timestamp` → material-storage 三表(download / signed_url / approval) JOIN by `seafile_repo_id + seafile_path` 并按时间窗口对齐

**查询接口设计**:material-storage admin 调 Seafile `GET /api/v2.1/activities/?repo_id=X&start=Y&end=Z`,获 activity 流,本地按 `share_link_token` join 出真实 actor;查询结果保留 Seafile activity 原行 + material-storage augment 列,Web UI 单表展示。

---

## 8. 与飞书契约的关联

| 契约 | 与本文档的关系 |
| --- | --- |
| [MS-FB-001](../feishu/contracts/approval.md) `approval.md` | `approval_audit` 行的字段来自 MS-FB-001 webhook payload(`approval_id` / `current_status` / `decided_by` / `comment` 等);**ground truth 走 MS-FB-007 GET**,本表只是 projection |
| [MS-FB-002](../feishu/contracts/identity.md) `identity.md` | user snapshot 列(`open_id_snapshot` / `name_snapshot` / `email_snapshot` 等)的字段定义沿用 MS-FB-002;`email` 可 null 语义沿用 |
| [MS-FB-004](../feishu/contracts/sso.md) `sso.md` | `admin_session_audit.bridge_sub` 来自 MS-FB-004 id_token / userinfo `sub` claim;bridge OIDC session id 是 MS-FB-004 v1 未约定字段,本表预留 nullable |
| [MS-FB-007](../feishu/contracts/approval-seafile.md) `approval-seafile.md` | `signed_url_audit.seafile_approval_id` + `approval_audit.seafile_approval_id` 直接对应;MS-FB-007 §7 audit gap 是本文档核心 motivating point(见 §3 表 ★ 行) |

---

## 9. v1 不实现 / 未决

| # | 项 | 说明 |
| --- | --- | --- |
| 1 | 完整 export API spec(字段过滤 / multi-format / 分页协议) | 等 admin UI requirement 落地;v1 仅 CSV stream by user/time/type |
| 2 | 签名 URL revocation log 详细字段(撤销原因 / actor) | 等 FastAPI 代理 PoC 跑过,看真实场景需求 |
| 3 | PII classification taxonomy(GDPR 形状字段标记 / 自动脱敏) | 字段**已预留 snapshot 列结构**,具体 PII 标记规则待业务侧 IT 决定后加 |
| 4 | 跨实例审计 shipping(SIEM / Logstash) | 单实例足够;多实例 / 异地归集 v1.x 评估 |
| 5 | 留存自动清理(`DROP PARTITION` 调度) | deployment 决定;v1 仅给"按月分区"提示 |
| 6 | 审计行篡改检测(hash chain / write-once 存储) | 内部审计可信,合规升级时再加;v1 假设 DB 主从复制 + RO 备份足够 |
| 7 | 实时审计 dashboard / SIEM 推送 | 业务 UI 落地后评估 |
| 8 | 写入失败的兜底队列(material-storage 进程崩了 webhook 丢) | 旁路系统设计;实施时落 redis stream / kafka,不在本审计 schema 范围 |

---

## 10. 向后兼容承诺(v1 → 未来)

| 变更类型 | v1 → v1.x | v2 |
| --- | --- | --- |
| 新增 event_type 枚举值(任一表) | ✓(消费方未识别按 unknown 处理) | — |
| 新增 nullable 字段 | ✓ | — |
| 改 PK / 改字段类型 / 删字段 | ✗ | ✓ |
| 切到 hash chain 审计 | ✓(并行新表;旧表不动) | — |
| 改 dedup_key 格式 | ✗(已有数据 dedup 失效) | ✓ |
| 改留存策略 | ✓(运维操作,不动 schema) | — |

---

## 11. 关联

- [ADR-0001](decisions/0001-no-full-custom-web-ui.md):敏感目录代理路径 → `download_audit kind=proxy` 由本表 SoT
- [ADR-0002](decisions/0002-feishu-contacts-as-identity-source.md):`internal_user_id` PK + 外部账号 + 离职闭环 → 本文档 §1.1 / §1.2 / §4 snapshot 列设计
- [ADR-0003](decisions/0003-seafile-only-poc.md):v0.5 Seafile only + F-X(Seafile audit log = service account)→ 本文档 §3 motivating row
- [file-management-system.md v0.5](research/file-management-system.md):§3.2 主动转码代理版 → `sidecar_task_audit` 字段设计
- [MS-FB-001](../feishu/contracts/approval.md) / [MS-FB-002](../feishu/contracts/identity.md) / [MS-FB-004](../feishu/contracts/sso.md) / [MS-FB-007](../feishu/contracts/approval-seafile.md):见 §8
- Issue #16(本文档驱动 issue)
