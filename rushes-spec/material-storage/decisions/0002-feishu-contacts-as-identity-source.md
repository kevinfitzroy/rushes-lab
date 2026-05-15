# ADR-0002: 采用飞书通讯录作 material-storage 身份源 (SoT)

- **状态:** accepted
- **日期:** 2026-05-15
- **决策者:** user + material-storage agent
- **关联:**
  - 调研:[`../../feishu/research/contacts-as-identity-source.md`](../../feishu/research/contacts-as-identity-source.md)(feishu agent 出品)
  - 驱动 issue:[#6](https://github.com/kevinfitzroy/rushes-lab/issues/6)
  - 契约:`rushes-spec/feishu/contracts/identity.md`(尚未起草,即 MS-FB-002 的实现)
  - 飞书侧 ADR:[`../../feishu/decisions/0001-approval-channel.md`](../../feishu/decisions/0001-approval-channel.md)

## 背景

方案 v2 默认 LDAP/AD 作身份源。飞书审批通道选定后(2026-05-15),浮现一条简化路径:"飞书通讯录直接作 SoT,不部署 LDAP/AD"。

material-storage agent 通过 issue #6 委托 feishu agent 评估;feishu agent 调研报告(`rushes-spec/feishu/research/contacts-as-identity-source.md`)实证可行:

- 核心员工字段(姓名 / 部门 / 职级 / 入职 / 离职状态)完整暴露
- 离职闭环:`contact.user.deleted_v3` 事件携带 `old_object`,可知员工离职前完整状态
- `open_id` 应用域不回收(单应用场景作内部主键稳定)
- 同步策略:事件订阅 + 每日全量对账兜底

调研同时识别 3 条边界 + 1 条未实测 caveat,见下 "影响" 节。

## 决策

material-storage 的**用户身份 SoT = 飞书通讯录**。LDAP/AD 整层**不部署**。

material-storage 本地仍维护以下与 SoT 解耦的字段(由 ADR-0001 业务策略层承担):

- 角色 → 资源类别映射(business mapping)
- 审批人路由规则(在 MS-FB-005 之外的本地兜底)
- 下载配额 / 速率限制
- 审计日志(全本地,合规要求)
- **外部账号表**(临时合作方,不进飞书企业)
- 用户行为(最近访问 / AI 推荐反馈)
- Notification preferences

内部员工身份来源:飞书 SSO(走 MS-FB-004 / OAuth user_access_token) → JIT provisioning 创建本地账号。

## 影响

### 字段策略

- material-storage 内部 user 表 PK = 自建 `internal_user_id`(数据库主键,与飞书 ID 解耦,便于未来更换 IM)
- 外键到 飞书 `open_id`;同时保存 `union_id` 备份(应对未来挂同一 ISV 的多飞书应用场景)
- **不**使用飞书 `user_id`(企业内部短 id,回收行为飞书未明确)

### 离职闭环

- bridge 收 `contact.user.deleted_v3` 事件 → material-storage 收 webhook → 立即:
  - 标记账号 `inactive`
  - 撤销所有活跃 session + 已签发签名 URL
  - 标记其未决审批为 `invalid`
- 每日凌晨 bridge 全量对账(`find_by_department` 遍历)+ material-storage 复核状态一致性

### mobile / email 策略(基于调研 §5)

- `email`:走 OAuth `user_access_token`(MS-FB-004 SSO)首次登录拿邮箱并落库,不要 IT 后台全局开放应用读取邮箱 — scope 最小化 + 用户主动同意
- `mobile`:暂不取(目前无短信通知场景)
- `enterprise_email`:同 email 处理

### 外部账号(基于调研 §4)

- material-storage 自维护 `external_users` 表,与飞书 SoT 完全解耦
- 字段:邮箱、姓名、过期时间、邀请人 `open_id`、用途等
- 临时下载场景走"邮箱 OTP + 一次性签名链接"路径,**不**注册到飞书企业(避免占人头 + 减少外部 UX 摩擦)
- 审批人路由(若需要)由邀请人作为兜底审批人

### MS-FB-002 契约输入

bridge 暴露给 material-storage 的"身份解析"接口,字段集合按调研 §8.3 + 本 ADR 补建议:

```
GET /v1/users/by-open-id?open_id=ou_xxxx
→ {
    open_id, union_id, name, en_name?,
    email?, enterprise_email?, mobile?,
    department_chain: [{open_department_id, name, is_primary}, ...],
    job_level_id?, job_title?,
    employee_no?, employee_type, join_time,
    status: { is_resigned, is_frozen, is_unjoin },
    is_tenant_manager,
    manager_open_id?,             // material-storage agent review 补建议:MS-FB-005 路由用
    is_external: bool,            // 补建议:false=飞书 SoT, true=material-storage 自管(本接口仅返回 false)
    last_synced_at                // bridge 缓存时间戳
}
```

`is_external=true` 的查询由 material-storage 自己处理,不走 bridge。

### Bridge 角色范围

调研结论使 bridge 的角色比初始假设更重:

- 本地通讯录缓存(事件订阅 + 全量对账)
- 可能充当企业 micro-IdP(OIDC provider,供底座 NC/oCIS 接入,见 ADR-0003 待写)

这部分是 feishu agent 实施范围,material-storage 在 review 飞书侧契约 + ADR 时关注。

## Caveats

- ⚠️ **离职后 `tenant_access_token` 下 GET 行为未直接实测**(调研 §2.1)。结论基于:(a) SDK 把 `is_resigned` 列为常规字段;(b) OAuth `user_access_token` 路径 20021 与 `/contact/v3/*` 是两套不同接口。**MS-FB-002 实施 PoC 阶段须补实测,见 issue #6 调研 §9 待办 #1**。若实测发现 GET 返回 404 或字段不完整,需调整 bridge 缓存策略 — 但**不影响**本 ADR 的核心决策。
- 离职事件丢失风险:webhook 偶发丢失场景下,每日全量对账是兜底
- 用户组(`group`)成员变更**无事件**,要轮询 — material-storage 若用 group 做权限映射,需接受滞后

## 备选方案与拒绝理由

### A. LDAP/AD 作 SoT

- IT 部署 + 备份 + 高可用 + 字段维护投入显著
- 飞书事件机制 + `is_resigned` 等天然字段在 LDAP 要业务侧自己实现
- **拒绝**:与"飞书已经是企业目录"现实重复,运维负担无理由

### B. 飞书 + LDAP 双 SoT 共存

- 飞书做主源,LDAP 做合规归档 / 或反过来
- **拒绝**:同步复杂度激增,无明显好处;离职闭环二次校对反而引入不一致风险

### C. 飞书自定义 `employee_type` 装外部合作方(让外部方也进飞书企业)

- 调研 §4 中讨论
- **拒绝**:占企业人数(按人头计费)+ 外部方 UX 摩擦(常无飞书或不愿装)+ 临时低权限不值得污染企业目录

### D. 飞书 SoT + material-storage 自管外部账号表(本决策方向)

- **接受**

## 变更日志

- 2026-05-15:初版 accepted
