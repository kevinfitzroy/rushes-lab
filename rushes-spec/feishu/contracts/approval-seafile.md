# Contract: Seafile 下载审批桥接 (approval-seafile) v1

## 能力描述

定义 `feishu-integration`(下称 **bridge**)在 **"Seafile 文件下载需走飞书审批"** 场景下,把以下三件事**串成单一上游接口**的契约:

1. 接收上游(FastAPI 旁路 / Seafile 插件)提交的"对某 Seafile 文件的下载申请"
2. 内部调用飞书审批 v4(通过 [MS-FB-001 `approval.md`](./approval.md) 的内部复用)
3. 审批通过后,调 Seafile `POST /api/v2.1/share-links/` 创建短期下载链接,通过飞书 IM 卡片**主动**推给申请人

**覆盖需求:** [issue #24](https://github.com/kevinfitzroy/rushes-lab/issues/24) WP2(MS-FB-007)。

**不覆盖:** Seafile SSO 接入(MS-FB-006 [`sso-seafile.md`](./sso-seafile.md));飞书审批本身(MS-FB-001 [`approval.md`](./approval.md));业务侧资源敏感度判定(material-storage 业务策略层负责)。

**调研依据:**
- MS-FB-001 [`approval.md`](./approval.md):审批底层契约
- MS-FB-006 [`sso-seafile.md`](./sso-seafile.md):requester 身份从哪来
- Seafile share-link API 源码:[`seahub/api2/endpoints/share_links.py`](https://github.com/haiwen/seahub/blob/master/seahub/api2/endpoints/share_links.py)
- material-storage v0.4 file-management-system §4 "敏感目录下载审批的挂载方式"

## 版本

- **当前版本:** v1
- **状态:** draft
- **变更日志:**
  - 2026-05-15: initial draft (feishu agent)

## 1. 角色与边界

| 角色 | 职责 | 实施方 |
| --- | --- | --- |
| 上游调用者 | 判定"这次下载是否走审批"、收集 requester 身份、调 bridge 提交申请、UI 展示状态 | FastAPI 旁路 / Seafile 插件,由 material-storage agent 实施 |
| **bridge (本契约)** | 串接飞书审批 + Seafile share-link + IM 通知 | feishu agent 实施 |
| 飞书审批中心 | 实际审批 UI / 状态机 | 飞书 |
| Seafile API | 生成下载链接 | Seafile Pro 服务器 |
| 飞书 IM | 推送结果给 requester | 飞书 |

**核心边界:** 上游**不直接调** Seafile share-link API,也**不直接调**飞书审批 API。所有跨系统调用收敛到 bridge。

## 2. 通用约定

### Base path

`/v1` 前缀(与 [`approval.md`](./approval.md) / [`identity.md`](./identity.md) 一致)。

### 认证

同 `approval.md`:`X-Bridge-Token: <token>` header,失败返 `401 unauthorized`。

### Content-Type

`application/json; charset=utf-8`。

### 时间表示

ISO 8601 UTC。

### 错误响应通用结构

```json
{
  "code": "<machine code>",
  "message": "<human description>",
  "details": { /* 可选 */ }
}
```

### 标识符约定

- `seafile_approval_id`:bridge 内部审批 id(UUIDv4,32-36 字符);区别于底层 `approval.md` 的 `approval_id` —— 一对一关系,但语义命名分开
- `requester_open_id`:申请人飞书 `open_id`(本应用域),由上游从 OIDC session 的 `feishu_open_id` claim 取得(见 [`sso-seafile.md`](./sso-seafile.md) §2)
- `seafile_repo_id`:Seafile 资源库 UUID
- `seafile_path`:资源库内文件路径,UNIX 风格,以 `/` 开头
- `share_link_token`:Seafile 生成的 share-link token(短字符串);删除 / 撤销时用

## 3. Endpoints

### POST `/seafile-approvals` — 发起下载审批

**用途:** 上游收到用户"我要下载这个文件"动作后,调用本接口。bridge:
1. 校验 requester(MS-FB-002 内部缓存,确认非 resigned / frozen)
2. 校验 Seafile 文件存在(`GET <SEAFILE_API_URL>/repos/{repo_id}/file/?p={path}` 简单 metadata)
3. 内部调用 [`approval.md`](./approval.md) `POST /approvals` 提交飞书审批,`approval_type` 固定 `resource_download`
4. 落库 `seafile_approval` 记录,关联底层 `approval_id`
5. 返回 `seafile_approval_id` + 初始 `pending` 状态

**Headers:**

| Header | 必填 | 说明 |
| --- | --- | --- |
| `X-Bridge-Token` | ✓ | — |
| `Idempotency-Key` | 推荐 | UUID;24h 内同 key 返回同 `seafile_approval_id`(同 `approval.md`) |

**Request body:**

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `requester_open_id` | string | ✓ | 申请人飞书 `open_id`(从 OIDC session `feishu_open_id` claim 取) |
| `seafile_repo_id` | string | ✓ | Seafile 资源库 UUID |
| `seafile_path` | string | ✓ | 文件路径,以 `/` 开头 |
| `reason` | string | ✓ | 申请理由,1 ≤ len ≤ 500 |
| `expire_days` | integer | 否 | share-link 有效期天数;默认 `7`;范围 `[1, 30]`(超出 `400 invalid_expire_days`) |
| `password_required` | bool | 否 | share-link 是否带访问密码;默认 `false`。`true` 时 bridge 自动生成 8 位高熵密码,**通过同一张 IM 卡片**推给 requester。**密码不会通过本契约 GET 接口暴露给上游服务**(见 §3 GET 字段说明) |
| `metadata` | object | 否 | 透传到飞书审批表单的键值对,例如 `{"category": "case_library", "client_name": "..."}`;**bridge 直接转发到底层 [`approval.md`](./approval.md) `POST /approvals` 的 `metadata` 字段,不做转换**;两层 metadata 物理同一份 |

**Request 示例:**

```json
{
  "requester_open_id": "ou_a3935e60b01fd60679ce671cee771c6b",
  "seafile_repo_id":   "abc123-...-def456",
  "seafile_path":      "/case-lib/2025/q4/clip-019.mp4",
  "reason":            "客户案例汇报需要原片素材",
  "expire_days":       7,
  "password_required": true,
  "metadata":          { "category": "case_library" }
}
```

**Response 200:**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `seafile_approval_id` | string | bridge 内部 id |
| `approval_id` | string | 底层 [`approval.md`](./approval.md) approval_id,**作上游侧 cross-system 追踪用**;上游可单独调 GET `/approvals/{approval_id}` 看底层审批细节 |
| `status` | enum (`pending`) | 初始 |
| `created_at` | string (ISO 8601 UTC) | bridge 落库时刻 |

**Errors:**

| HTTP | `code` | 含义 | 客户端建议 |
| --- | --- | --- | --- |
| 400 | `invalid_request` | JSON 缺字段 / 类型错 / reason 超长 | 修请求 |
| 400 | `invalid_expire_days` | `expire_days` 越界 | 修请求 |
| 401 | `unauthorized` | bridge token 校验失败 | — |
| 404 | `requester_not_found` | `requester_open_id` 在 MS-FB-002 缓存与飞书中查不到 | 上游应清理本地引用 |
| 410 | `requester_resigned` | 申请人已离职 | UI 拒绝并友好提示 |
| 404 | `seafile_resource_not_found` | Seafile 侧文件不存在 / repo 不存在 | 上游应同步 Seafile 元数据 |
| 503 | `seafile_upstream_unavailable` | Seafile API 不可达;bridge 内部已重试 | 退避 |
| 503 | `feishu_upstream_unavailable` | 飞书审批 API 不可达;同上 | 退避 |
| 409 | `idempotency_conflict` | 同 `Idempotency-Key` 上次请求 body 不一致 | 换 key |
| 500 | `internal_error` | bridge 故障 | 重试 + 告警 |

---

### GET `/seafile-approvals/{seafile_approval_id}` — 查询单条

**用途:** 上游 UI "立即刷新"按钮 / 对账。日常状态变化**不**靠轮询,见 §"运维约定"。

**Response 200:**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `seafile_approval_id` | string | — |
| `approval_id` | string | 底层 approval_id |
| `requester_open_id` | string | — |
| `seafile_repo_id` / `seafile_path` | string | — |
| `status` | enum(见 §5 状态机) | — |
| `previous_status` | enum \| null | 上一状态;`pending` 时为 `null` |
| `decided_by` | string \| null | 终态决策者 `open_id`;非终态为 `null` |
| `decided_at` | string (ISO 8601 UTC) \| null | 进入当前状态的时间 |
| `share_link_url` | string \| null | 仅 `status=approved` 且 share-link 已成功创建时有值;否则 `null` |
| `share_link_expires_at` | string (ISO 8601 UTC) \| null | 同上;`approved` 后 bridge 算出的过期时间 |
| `share_link_password_set` | bool | 仅当 `status=approved` 时有意义。`true` 表示该 share-link 启用了密码保护;**明文密码不通过本接口暴露**,仅 IM 卡片推送给 requester。上游需要"我用过密码"佐证审计时,查 bridge 内部的 IM 推送日志(`message_id`),不要本字段暴露明文 |
| `metadata` | object | 透传 |
| `created_at` | string (ISO 8601 UTC) | bridge 落库时刻 |

**Errors:** 同模式,主要 `404 not_found` / `401 unauthorized` / `500`。

---

### POST `/seafile-approvals/{seafile_approval_id}/withdraw` — 申请人撤销

**用途:** 仅 requester 可撤销;调用 [`approval.md`](./approval.md) `withdraw` + 若 share-link 已生成则一并 `DELETE`。

**Request body:**

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `actor_open_id` | string | ✓ | 必须等于 `requester_open_id`,否则 `403 forbidden_actor` |
| `reason` | string | 否 | ≤ 200 字 |

**Response 200:**

```json
{
  "seafile_approval_id": "...",
  "status": "withdrawn",
  "decided_at": "2026-05-15T..."
}
```

**Errors:**

| HTTP | `code` | 含义 |
| --- | --- | --- |
| 401 | `unauthorized` | — |
| 403 | `forbidden_actor` | actor 非 requester |
| 404 | `not_found` | seafile_approval_id 不存在 |
| 409 | `cannot_withdraw_terminal_state` | 已是 approved / rejected / withdrawn / expired |
| 503 | `seafile_upstream_unavailable` | share-link 撤销失败(approved 状态下撤销需要 DELETE Seafile,失败) |
| 503 | `feishu_upstream_unavailable` | — |

---

## 4. bridge 内部工作流(实施约束,非契约面)

```
T0: POST /seafile-approvals
    ├─ MS-FB-002 GET user(requester_open_id) 校验
    ├─ Seafile GET file metadata 校验
    ├─ MS-FB-001 POST /approvals { applicant_open_id: requester_open_id,
    │                              approval_type: "resource_download",
    │                              resource_ref: "<repo_id>:<path>",
    │                              reason, metadata }
    │   → 飞书侧创建审批实例,审批人收到飞书通知
    ├─ 落库 seafile_approval { id, approval_id, repo_id, path, status=pending, ... }
    └─ 返回 seafile_approval_id + approval_id

T1: 审批人在飞书 App 操作(通过 / 拒绝)
    └─ 飞书事件 → bridge `/api/lark/callback`(MS-FB-001 实施代码已接管)
       └─ bridge 触发内部 `on_approval_status_changed(approval_id, status)`:
          - status=approved:
              ├─ Seafile POST /api/v2.1/share-links/ {
              │    repo_id, path, expire_days,
              │    password (若 password_required) }
              │   → 返回 share_link_token + 完整 URL
              ├─ 更新 seafile_approval { status=approved, share_link_*, decided_*}
              ├─ 飞书 IM 推卡片给 requester(见 §6 IM card 格式)
              └─ (现有 MS-FB-001 webhook 仍照常向上游推 approval.status_changed)
          - status=rejected:
              ├─ 更新 seafile_approval { status=rejected, decided_* }
              ├─ 飞书 IM 推"拒绝"卡片给 requester(含 comment)
              └─ (同上 MS-FB-001 webhook 触发)
          - status=withdrawn:
              ├─ 若 share-link 已创建:Seafile DELETE /api/v2.1/share-links/{token}/
              ├─ 更新 seafile_approval { status=withdrawn, decided_* }
              └─ 不推 IM(由 requester 主动撤销)

T2 (可选 v1.x): bridge 定时任务
    └─ 每小时扫描 status=approved 且 share_link_expires_at < now 的记录,
       置 status=expired(仅本契约视角,Seafile share-link 已自然失效)
```

## 5. 状态机

```
pending ─┬─→ approved   (审批人通过 + Seafile share-link 创建成功)
         ├─→ approved_link_failed   (审批通过但 Seafile share-link 创建失败,异常态)
         ├─→ rejected   (审批人拒绝)
         └─→ withdrawn  (申请人撤销;若已有 share-link 同步 DELETE)

approved ─→ expired  (share-link 自然过期,由 bridge 定时任务标记,v1.x)
```

**终态:** `approved` / `approved_link_failed` / `rejected` / `withdrawn` / `expired`。

**`approved_link_failed`(异常态)行为:**
- 飞书侧审批 = APPROVED 但 bridge 调 Seafile share-link API 失败(网络 / Seafile 5xx / Seafile API token 失效)
- bridge 内部**自动重试 3 次**(指数退避 30s / 5min / 1h);全失败置 `approved_link_failed`
- 该状态下,**飞书 IM 推送"系统异常,请联系管理员"卡片**给 requester
- 运维介入后,可调 v1.x 后续 endpoint `POST /seafile-approvals/{id}/retry-link` 重试(v1 不实现)

## 6. 飞书 IM 卡片(主动推送)

> v1 **内联**简化卡片定义。MS-FB-003(消息卡片推送契约,待起草)定型后,本契约切到 MS-FB-003 调用是 v1.x 演进。

bridge 通过飞书 `POST /open-apis/im/v1/messages` 推 `interactive` 卡片给 `requester_open_id`,卡片含:

| 状态 | 卡片内容(摘要) |
| --- | --- |
| `approved` | 标题:"下载已通过"<br>正文:文件路径、有效期(`expire_days` 计算)、若 `password_required` 含密码<br>按钮:"打开下载链接"(跳 share_link_url) |
| `rejected` | 标题:"下载被拒绝"<br>正文:审批人备注 `comment`<br>按钮:"重新申请"(透传到 material-storage UI,深链格式由实施定) |
| `approved_link_failed` | 标题:"系统异常"<br>正文:"审批已通过但下载链接生成失败,请联系管理员"<br>无按钮 |

**v1 不实现:**
- 卡片交互回调(用户点按钮的飞书 webhook 处理)—— 按钮纯粹是 URL 跳转
- 卡片国际化 —— v1 仅中文
- 卡片 template_id 模板化 —— v1 用 hardcode 卡片 JSON

### 6.1 安全提示(运维 / 审计须知)

share-link URL 通过飞书 IM 卡片推送给 requester,**链接随即出现在飞书企业 IM 历史里**:
- 可被 IM 搜索功能搜索
- 可被用户多设备同步(手机 + PC)
- 可被截屏或对外转发
- 一旦泄漏到 IM 之外,飞书 IM 本身无法回收

设计依赖 **`expire_days` 限期 + `password_required` 双因素**来限制链接被分享后的可用性。**链接本身不可视作机密**;若资源敏感度要求"链接绝不能离开 requester",本契约不适用,需要单独设计"短期凭据 + 实时审计 + IP 锁定"等加强方案(v1.x 评估)。

## 7. bridge 配置(env)

| env | 用途 | 备注 |
| --- | --- | --- |
| `SEAFILE_API_BASE` | Seafile API base URL,例 `https://seafile.internal/api/v2.1` | 不含 trailing slash |
| `SEAFILE_API_TOKEN` | Seafile service-account API token,需有"创建任意资源库 share-link"权限(通常 = admin) | **不入 git**;0600 / env |
| `SEAFILE_OPS_USERNAME` | 上述 token 对应的 Seafile username(供 audit log 标识 service account) | 推荐 `bridge-service@feishu` 或类似 |

## 8. 向后兼容承诺(v1 → 未来)

| 变更类型 | v1 → v1.x(允许) | v1 → v2(必要) |
| --- | --- | --- |
| 新增 request body 可选字段 | ✓ | — |
| 新增 response 字段 | ✓ | — |
| 新增 IM 卡片字段(`approved` 卡片加"下载次数限制"显示) | ✓ | — |
| 新增 status 枚举值 | ✗(上游处理不到新值会漏)| ✓ |
| 改字段类型 / 改 path | ✗ | ✓ |
| `approved_link_failed` 异常态语义变更 | ✗ | ✓ |
| 切到 MS-FB-003 调用做 IM 推送(替代内联) | ✓(对上游透明) | — |

## 9. 与上游(material-storage)的运维约定

### 9.1 状态变化感知:**MS-FB-007 GET 是 ground truth,MS-FB-001 webhook 仅作提示**

> ⚠️ **关键时序约定:** 底层 [`approval.md`](./approval.md) 的 `approval.status_changed` webhook 推送 `approved` 时,**share-link 可能尚未创建成功**(`approved_link_failed` 异常态,见 §5)。上游收到 MS-FB-001 webhook 的 `approved` **不能**直接判定"下载已就绪",必须再调本契约 `GET /seafile-approvals/{id}` 拉 ground truth(`status` + `share_link_url`)。
>
> 推荐消费模式:
> 1. 上游消费 MS-FB-001 `approval.status_changed` webhook,收到 `current_status=approved`
> 2. **立即** GET 本契约 `/seafile-approvals/{id}`(关联 key:POST 响应里返的 `approval_id`,上游应双存 `{approval_id, seafile_approval_id}`)
> 3. 检查响应的 `status`:
>    - `approved` + `share_link_url` 非 null → 下载就绪
>    - `approved_link_failed` → 通知运维 / UI 展示异常
>    - 其他状态 → 等待下次 webhook(罕见 race condition)

### 9.2 Share-link URL 流转

- 仅通过飞书 IM 卡片**主动推送给 requester**(见 §6)
- **同时**通过本契约 GET 接口对上游可见(上游 UI"我的下载"等场景用)
- **链接 + 密码是双因素**;链接本身**不视为机密**(因为通过 IM 推送 = 链接在飞书企业 IM 历史里可被搜索,见 §6 安全提示)

### 9.3 Share-link 密码

- v1 通过 IM 卡片同卡推送 requester
- 上游**不可见明文密码**(本契约 GET 返 `share_link_password_set: bool`,不返 string)
- 审计可见 IM message_id 而非密码原文

### 9.4 离职闭环

上游收 MS-FB-002 `user.status_changed` webhook 时,若 `change_type=resigned`,应主动调本契约 GET 查该用户所有未终态 `seafile_approval`,**调 withdraw** 触发 share-link DELETE;**bridge 本身不主动触发**(避免重复事件 + 边界判定)

## 10. v1 不实现 / 未决

1. **share-link 下载次数限制** —— Seafile share-link API 有 `download_link_password` 等字段但 Seafile CE/Pro 对"下载次数"原生支持有限,实测后定;v1 仅暴露过期天数
2. **share-link 主动撤销 webhook 给上游** —— v1 上游靠"自己提交的 seafile_approval 走完状态机"即可推断 share-link 状态;v1.x 评估加 `share_link.revoked` 事件
3. **batch 提交** —— v1 单次只支持一份审批;多文件下载 v1 要求上游拆多次
4. **share-link 续期** —— v1 过期后只能重新申请;v1.x 评估"续期"endpoint
5. **重试已失败的 share-link 创建** —— v1 `approved_link_failed` 终态后不可恢复;v1.x 加 retry endpoint
6. **Seafile CE 兼容** —— v1 假设 Seafile **Pro**(material-storage 已敲定);CE 部分 API 行为不同,需要 PoC 实测后回写

## 11. 与其他契约的关系

- [`approval.md`](./approval.md) (MS-FB-001):**本契约内部依赖**;`POST /seafile-approvals` 内部转化为 `POST /approvals`;状态变更靠 MS-FB-001 现成 webhook;**没有**用 MS-FB-001 没暴露的飞书审批 v4 字段
- [`identity.md`](./identity.md) (MS-FB-002):requester 身份校验 + 离职闭环;bridge 内部读 MS-FB-002 缓存
- [`sso-seafile.md`](./sso-seafile.md) (MS-FB-006):上游获取 `requester_open_id` 的源头(OIDC session `feishu_open_id` claim)
- MS-FB-003 消息卡片推送(待起草):本契约 §6 IM 卡片实施切到 MS-FB-003 是 v1.x 演进
- material-storage ADR-0001(业务策略层 + 审计日志 SoT 归 FastAPI):material-storage 是审计 SoT,本契约的 GET `/seafile-approvals/{id}` 是其审计数据来源之一

## 12. PoC 验收清单(Seafile Pro 到位 + MS-FB-001 实施完成后)

1. [ ] bridge 配置 `SEAFILE_API_BASE` / `SEAFILE_API_TOKEN`,startup 拉一次 Seafile `/account/info/` 验 token
2. [ ] 上游(测试脚本)调 `POST /seafile-approvals` → 飞书 App 收到审批通知
3. [ ] 审批人在飞书 App 点"通过" → bridge 自动创建 Seafile share-link → 飞书 IM 卡片推 requester,含完整 share-link URL
4. [ ] requester 在新隐私窗口打开 share-link URL,验证可下载文件
5. [ ] 拒绝流程:飞书"拒绝" → IM 卡片推"拒绝"含 comment;Seafile **无** share-link
6. [ ] 撤销流程:requester 调 withdraw(approved 状态下)→ Seafile share-link DELETE 成功 → 再访问 share-link 返 404
7. [ ] 异常态:故意配错 `SEAFILE_API_TOKEN`,触发 `approved_link_failed`,IM 卡片正确推送"系统异常"
8. [ ] 离职闭环:requester 在审批 pending 阶段被 IT 标记离职 → MS-FB-002 webhook → 上游(测试脚本)调本契约 withdraw → 飞书审批撤销,无 share-link 生成
