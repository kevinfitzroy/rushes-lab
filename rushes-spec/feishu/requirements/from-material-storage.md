# Requirements: from material-storage

> material-storage 对 `feishu-integration` 的功能需求清单。**material-storage agent 维护**,feishu agent 按此提案契约。
>
> 优先级:**P0** 必须 / **P1** 应有 / **P2** 可有

## 上下文

material-storage 是企业内部素材存储系统(短视频为主,~100 TB,~50-100w 文件);飞书是该系统的审批通道与身份/通知渠道。详见 [`../../material-storage/README.md`](../../material-storage/README.md) 与 [`../../material-storage/research/file-management-system.md`](../../material-storage/research/file-management-system.md)。

material-storage 的实施目录 [`../../../material-storage/`](../../../material-storage/) 目前为空,实施未启动;但因为飞书侧可以独立先行(契约稳定即可),先把需求落清。

## 需求清单

### MS-FB-001:审批申请 / 状态查询 / 撤销 [P0]

**业务背景:** material-storage 需要在两种场景发起飞书审批:
- 敏感资源下载(单次,通过即签发短期签名 URL)
- 临时权限申请(默认 7 天,通过后 IT 在身份源加入临时组 —— 身份源待 Q2 决定)

**期望行为:**

1. `POST /approvals`:接收申请上下文,返回 `approval_id` + 初始状态
2. `GET /approvals/:id`:查询单条状态
3. `POST /approvals/:id/withdraw`:申请人主动撤销
4. 通过事件 webhook 向 material-storage 推送状态变更(`pending` → `approved` / `rejected` / `withdrawn` / `expired`)

**输入(草案,具体走契约):**

- `applicant`:申请人内部 user id 或 飞书 open_id(看身份策略)
- `approval_type`:`resource_download` / `temp_permission`
- `resource_ref`(下载场景):资源唯一标识
- `target_path`(临时权限场景):目标目录路径
- `reason`:申请理由
- `metadata`:键值对(下载有效期、资源类别等),透传到飞书审批表单

**输出:**

- `approval_id`(bridge 内部 ID)
- `feishu_instance_code`(透传)
- `status`

**Webhook 事件 schema(草案):**

```json
{
  "event_type": "approval.status_changed",
  "approval_id": "...",
  "previous_status": "pending",
  "current_status": "approved",
  "decided_by": "<open_id>",
  "decided_at": "2026-05-15T12:34:56Z",
  "comment": "..."
}
```

**幂等性:** webhook 必须可重投,material-storage 侧按 `approval_id + current_status` 去重。

**验收标准:**

- 上游调一次 `POST /approvals`,飞书审批中心出现条目;审批人通过/拒绝后 60 秒内 webhook 投递成功
- 重试 4 次的事件(飞书侧重试)material-storage 侧无副作用
- 撤销后状态正确同步

---

### MS-FB-002:用户身份解析(open_id 映射)[P0]

**业务背景:** material-storage 内部用户 ID(可能是 email、internal_uid 或飞书 open_id 本身,看 Q2 身份源选型)需要解析到飞书 open_id 才能发起审批和发通知。

**期望行为:**

- `GET /users/by-internal-id?internal_id=xxx` → 返回 `open_id`、`name`、`department_chain`
- `GET /users/by-email?email=xxx@…` → 同上(用于身份源是 LDAP 时的 fallback)
- bridge 内部应维护 internal_id ↔ open_id 的映射缓存(由通讯录同步任务维护)

**待定:** 这条需求的具体输入字段取决于 Q2 身份源决策。**当前为占位**,身份源敲定后 material-storage agent 会更新本条。

**验收标准:**

- 已离职员工查询返回 `404 not_found` + 明确错误码
- 单次解析 P99 < 100ms(命中缓存)/ < 500ms(回源飞书 API)

---

### MS-FB-003:消息 / 卡片推送 [P1]

**业务背景:** material-storage 主动通知员工:
- 你的审批已通过 / 拒绝
- 你的下载签名 URL 已签发(附短期链接)
- 你申请的资源访问到期

**期望行为:**

- `POST /messages`:发送一条消息(文本或交互卡片)给指定 open_id
- 支持卡片模板(template_id 由飞书后台配置,bridge 暴露 template_id + 变量填充)

**输入(草案):**

```json
{
  "recipient_open_id": "...",
  "message_type": "text" | "card",
  "content": "...",            // text
  "card_template_id": "...",   // card
  "card_variables": { ... }
}
```

**验收标准:**

- 发送失败有明确错误码(用户已离职 / 模板不存在 / 飞书侧 5xx)
- bridge 内部对飞书 API 限频做退避

---

### MS-FB-004:网页授权(SSO)[P0]

**业务背景:** 员工通过飞书登录 material-storage Web UI。

**期望行为:**

1. material-storage Web 跳转到 bridge 暴露的 `/oauth/start?redirect_uri=...` → 由 bridge 跳到飞书授权 URL
2. 飞书回调 bridge 的 `/oauth/callback?code=...` → bridge 换 token、拿 `open_id` + 基本信息
3. bridge 把结果重定向回 `redirect_uri`,带上 bridge 签发的 short-lived JWT 或 session token

**安全要求:**

- `state` 参数防 CSRF
- `redirect_uri` 必须在 bridge 配置的白名单内
- bridge 签发的 token 必须有过期时间

**验收标准:**

- 一次完整 SSO 流程 < 3 秒(含飞书 RTT)
- 重放攻击不可能

---

### MS-FB-005:审批人路由(根据上下文解析审批人)[P1]

**业务背景:** material-storage 不希望硬编码"哪类资源该谁审批",请 bridge 根据规则解析。

**期望行为:**

- `GET /approval-routing?approval_type=resource_download&resource_category=case_library&applicant_open_id=xxx`
- 返回审批人链:`[{open_id, role, order}]`

**实现策略(建议给 feishu agent 参考):**

- 初期可在 bridge 内部硬编码规则表(yaml 配置)
- 长期可对接飞书"部门架构"+ 业务系统的"资源分类",动态计算
- 规则未命中时返回明确 `404 routing_not_found`,material-storage 侧 fallback 到"全员通用审批人"

**验收标准:**

- 规则修改后 5 分钟内生效(热加载或 SIGHUP)

---

### MS-FB-006:健康检查 [P2]

**期望行为:** `GET /healthz` 返回:

- bridge 自身健康
- `tenant_access_token` 是否可成功刷新(最近一次成功时间)
- 飞书 API 是否可达(轻量 ping)
- 通讯录同步任务状态

material-storage 可挂在自己的监控里。

---

## 变更日志

| 日期 | 变更 | 谁 |
| --- | --- | --- |
| 2026-05-15 | 初版,6 条需求 P0×3 / P1×2 / P2×1 | material-storage agent |
