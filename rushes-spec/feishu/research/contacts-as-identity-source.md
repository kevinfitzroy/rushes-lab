# 调研:飞书通讯录直接作 material-storage 身份源 (SoT)

> **调研日期:** 2026-05-15
> **版本:** v0.1
> **驱动 issue:** [#6](https://github.com/kevinfitzroy/rushes-lab/issues/6) — material-storage agent 委托 feishu agent 评估"飞书通讯录直接作 SoT、砍掉 LDAP/AD"路线的可行性
> **测试上下文:** 应用 `cli_aa8c58fae5391be7`,租户 `rusheslab.taoxiplan.com`,测试者 = 飞书 tenant 管理员
> **结论摘要(TL;DR):**
> - **核心员工 SoT 可行,推荐采纳。** 通讯录 API 字段集合丰富、状态(`is_resigned` / `is_frozen` / `is_exited` / `is_unjoin`)在 GET 响应与事件 payload 里完整暴露,`union_id` 保证唯一不回收。
> - **关键缺口 1:** 飞书开放平台**不暴露**"外部联系人"API。外部合作方 / 短期访客若要进 material-storage,要么走"飞书内部建访客账号(自定义 `employee_type`)+ 视为内部员工管理",要么单独维护一套不靠飞书的临时账号体系。**这条要 material-storage agent 拍板**。
> - **关键缺口 2:** 用户组(`group`)**没有事件订阅**,成员变更只能轮询;若 material-storage 要用"用户组"做权限映射,要接受最长 1 个同步周期的滞后。
> - **关键缺口 3:** `mobile` / `email` 等敏感字段在 `tenant_access_token` 下**默认为空字符串**,要拿这些需要走用户授权 (`user_access_token`) 或单独申请字段权限并由用户主动同意。这影响 material-storage 是否能拿员工邮箱作业务用户名/通知触达。

## 0. 方法论与证据来源

本报告区分三类证据,以便后续接手者校正:

| 标记 | 含义 |
| --- | --- |
| **(实测)** | 2026-05-15 用 PoC 服务的 `tenant_access_token` 真实调用 `/contact/v3/*` API,在测试租户拿到响应 |
| **(SDK)** | 从 `larksuite/oapi-sdk-python` 等官方仓库的代码生成模型推断的字段集合 / 事件名(高可信,但仍可能存在 SDK 滞后于 API 的偏差) |
| **(文档)** | 飞书开放平台官方文档(`open.feishu.cn`)的描述。注意官方文档站是 SPA,WebFetch 不可直接取,以参考资料引用列出 URL |

未标记的语句是综合上述证据后的**结论或推论**。

## 1. 通讯录 API 能力边界(回答 issue Q1)

### 1.1 主资源

`contact/v3` namespace 提供以下资源(实测路径前缀均为 `/open-apis/contact/v3`):

| 资源 | 关键接口 | 实测可调 |
| --- | --- | --- |
| **用户 (user)** | `GET /users/:user_id`、`GET /users/find_by_department`、`POST/PATCH/DELETE /users/:id`、`POST /users/batch_get_id`(手机/邮箱反查) | ✅(读) |
| **部门 (department)** | `GET /departments/:id`、`GET /departments/:id/children`、`POST/PATCH/DELETE /departments/:id`、`GET /departments/parent`、`POST /departments/search` | ✅ |
| **应用可见范围 (scope)** | `GET /scopes`(应用能"看到"哪些用户 / 部门 / 群) | ✅ |
| **用户组 (group)** | `GET /group/:id`、`GET /group/simplelist`、`POST /group`(创建)、`GET /group/:id/member/simplelist`(成员列表)、`GET /group/member_belong`(用户所属组) | ✅(空表) |
| **角色 (functional_role)** | `POST /functional_roles`(建)、`PUT/DELETE /functional_roles/:role_id`、`POST /functional_roles/:role_id/members/batch_*`、`GET /functional_roles/:role_id/members` | ⚠️ **无 LIST 接口 + 无 GET 单角色 metadata + 无事件订阅**(**详见 §9.6 更新**,本行原描述"通过事件订阅"已被推翻)—— 应用只能手工预知 `role_id` |
| **职级 (job_level)** | `GET /job_levels`、`POST/PUT/DELETE /job_levels/:id` | ✅ |
| **职务 (job_title)** | `GET /job_titles`、`GET /job_titles/:id` | (未实测,SDK 路径存在) |
| **职务序列 (job_family)** | `GET /job_families`、`POST/PUT/DELETE /job_families/:id` | ❌(本应用未申请 `contact:job_family` scope,飞书返回 `99991672`)— 申请后可用 |
| **人员类型 (employee_type_enum)** | `GET /employee_type_enums`、`POST/PUT/DELETE` | (SDK) |
| **自定义字段定义 (custom_attr)** | `GET /custom_attrs`、(写操作走管理后台或单独申请) | ✅(测试租户为空) |
| **单位 (unit)** | 一组部门之上的逻辑分组 | (SDK) |

### 1.2 单用户字段(实测,2026-05-15)

`GET /open-apis/contact/v3/users/{open_id}?user_id_type=open_id` 返回 `data.user` 含以下字段(脱敏值列出,**核心字段集合**):

```json
{
  "open_id": "ou_...",
  "union_id": "on_...",
  "user_id": "25dg35ef",
  "name": "<姓名>",
  "en_name": "",
  "nickname": null,
  "email": "",              // 默认为空,需 IT 后台显式授权应用读取或走 user_access_token,见 §5
  "enterprise_email": null, // 同上
  "mobile": "",             // 同上
  "mobile_visible": true,
  "employee_no": "",
  "employee_type": 1,       // 1=正式, 自定义类型见 employee_type_enums
  "gender": 0,
  "city": "",
  "country": "",
  "work_station": "",
  "job_title": "",
  "is_tenant_manager": true,
  "join_time": 1685059200,  // Unix epoch s
  "department_ids": ["od-xxxxxxx"],            // 多部门归属
  "orders": [{                                   // 每个部门内的次序 + 主部门标记
    "department_id": "od-xxxxxxx",
    "department_order": 1,
    "is_primary_dept": true,
    "user_order": 0
  }],
  "status": {                                    // 见 §2 离职闭环
    "is_activated": true,
    "is_exited": false,
    "is_frozen": false,
    "is_resigned": false,
    "is_unjoin": false
  },
  "avatar": { "avatar_240": "...", "avatar_640": "..." },
  "custom_attrs": []        // 见 §1.3
}
```

事件 payload(`P2ContactUserDeletedV3` / `UpdatedV3` / `CreatedV3`)在 SDK 中额外定义了下列字段(`UserEvent` 模型):

- `positions[]`、`leader_user_id`、`dotted_line_leader_user_ids[]`(汇报关系)
- `time_zone`
- `job_level_id`、`job_family_id`
- `enterprise_email`、`nickname`
- 事件**带 `old_object`**(老值,SDK 文件 `p2_contact_user_deleted_v3.py`),即离职 / 更新事件能拿到员工最后一刻的所有字段

### 1.3 自定义字段 (custom_attrs)

- 是租户级配置,字段定义由 IT 在飞书管理后台或通过 `contact/v3/custom_attrs` 维护
- 字段类型(从 SDK `user_custom_attr.py` 模型可见,实测留待租户配后再验):枚举/文本/数字/选项/picture/href 等
- 用户字段表里的 `custom_attrs: []` 数组承载每个用户的具体值
- **可在审批表单中通过审批表单的"成员"控件回引**(`research/approval-integration.md` §4 模板 widget 支持成员选择),但**审批模板 form 字段本身不能直接展示用户的 custom_attr 值** —— 跨资源的展示要在调用方自己组装

### 1.4 部门字段(实测)

```json
{
  "department_id": "789456123",       // 企业内自定义短 id
  "open_department_id": "od-xxxxxxx", // 飞书自动生成的全局 id
  "parent_department_id": "0",
  "name": "研发部",
  "i18n_name": {"en_us": "", "ja_jp": "", "zh_cn": ""},
  "order": "2000",
  "member_count": 2,
  "primary_member_count": 2,           // 主部门人数,区分多归属
  "status": {"is_deleted": false}      // 部门删除标记同样暴露
}
```

- **多部门归属**通过 `user.department_ids[]` + `user.orders[].is_primary_dept` 表达
- **删除标记**(`status.is_deleted`)说明部门删除不立即物理消失,有过渡

### 1.5 用户组 vs 角色 vs 职级

material-storage 做权限映射时,这三者用途各异:

| 概念 | 性质 | API 完备性 | material-storage 适用场景 |
| --- | --- | --- | --- |
| **用户组 (group)** | 任意员工集合,可手工维护或动态 | 读 / 加成员 / 查归属 都有;**无事件** | 临时小组、跨部门项目组的权限映射 |
| **角色 (functional_role)** | 业务角色,可绑定"角色 + 部门 scope" | **无 LIST,无事件**,要预知 role_id | 部门负责人 / 业务管理员等明确职责 |
| **职级 (job_level)** | 公司职级体系(P5/P6 之类) | 读 / 写 全;事件未列在 contact 事件中 | 审批人路由的"主管职级"判断 |
| **职务 (job_title)** | 岗位名 | 读 / 写 | 标签,不适合做权限边界 |
| **职务序列 (job_family)** | 序列(研发 / 销售) | 读 / 写,需 `contact:job_family` scope | 弱权限边界 |

**建议:** material-storage 权限映射首选 **部门** + **职级**;用户组作为辅助;角色因 API 不完整暂不依赖,等飞书补充 LIST 接口或我们用事件订阅自建本地角色表。

## 2. 离职闭环(回答 issue Q2,**最关键**)

### 2.1 离职后 GET 返回什么

`user.status` 对象暴露五个布尔标志(实测):

| 标志 | 含义 | 触发场景 |
| --- | --- | --- |
| `is_activated` | 用户已激活 | 完成首次登录后 true |
| `is_unjoin` | **尚未加入企业**(已邀请未接受) | 邀请后未注册 |
| `is_resigned` | **已离职** | IT 在管理后台标记离职 |
| `is_exited` | **已退出企业** | 用户自行退出 |
| `is_frozen` | **被冻结** | IT 临时冻结(暂停服务) |

**关键事实:**

- (推论,**未实测**)`is_resigned = true` 后,`GET /users/:open_id` **应仍然返回**用户信息(不是 404),只是 `status.is_resigned` 置位。bridge 因此可以查到"曾经存在的离职员工"。证据基础:
  - SDK `user_event.py` 中 `UserStatus` 模型把 `is_resigned` 列为标准字段,意味着该字段在常规 GET 响应中也出现(SDK 没单独定义"离职用户精简响应"类型)
  - OAuth 路径离职后返回 20021,**应用视角 tenant 调用仍可读**:`/authen/v1/user_info` 与 `/contact/v3/users/:id` 是两个不同接口、两套不同凭证、两套不同后端逻辑(前者由用户授权驱动,后者由 tenant 授权驱动)
  - 实测租户 7 人(全在职)未能直接验证;**本条已上移到 §8.1 结论的明示 caveat 与 §9 未尽事项 #1**
- (文档)`GET /authen/v1/user_info`(对应 `user_access_token`)在用户离职后**返回 20021 错误码 `User resigned`**(见 [`refs/feshu/auth2.md`](../../../../refs/feshu/auth2.md))。也就是说**用户视角 OAuth 失效;应用视角 tenant 调用大概率仍能查到记录**,两条路径行为不同。

### 2.2 离职事件

`contact.user.deleted_v3` 事件触发条件 = IT 在管理后台触发"离职"动作。SDK 中事件 payload 结构:

```python
P2ContactUserDeletedV3Data {
    object: UserEvent,       # 当前状态(离职后)
    old_object: OldUserObject  # 离职前的最后状态
}
```

✅ **`old_object` 字段意味着 material-storage 拿到事件时,能看到员工离职前的全部字段**(部门、职级、邮箱等)。这是大多数 SoT 实现的 critical capability,飞书提供了。

### 2.3 open_id 回收(Q2 关键子问题)

- `open_id`:**应用作用域**;同一应用内,**不回收**(SDK 注释 + 文档明示)。新员工有新 `open_id`,不会复用离职员工的 ID。
- `user_id`:**企业作用域**;短字符串(本租户实测 8 字符);**未明确是否回收**。飞书文档措辞模糊,**建议 material-storage 不使用 `user_id` 作为内部稳定主键**,统一用 `open_id` 或 `union_id`。
- `union_id`:**ISV 作用域**(对同一开发者的多个应用唯一);不回收。

**结论:** material-storage 内部用户主键用 **`open_id`**(单应用)或 **`union_id`**(若以后挂同一 ISV 的多个应用),不用 `user_id`。

### 2.4 离职闭环时序(推荐方案)

```
飞书 IT 后台标记离职
       ↓ (≤ 数秒)
飞书发 contact.user.deleted_v3 事件 → bridge → material-storage
       ↓
material-storage 收事件:
  1. 标记该 open_id 用户状态 = inactive
  2. 立即取消其活跃 session / signed URL
  3. 标记其所有未决审批为 invalid
       ↓
后备:每日全量同步遍历 find_by_department,核对 status.is_resigned
       是否一致(防事件丢失)
```

## 3. 同步策略可行性(回答 issue Q3)

### 3.1 全量同步路径

> ⚠️ **本节描述已被 §9.5 实测推翻,正确路径见 §9.5。** 保留下文作为初版推测留档,实施时**以 §9.5 为准**。

飞书**不提供"列出全企业用户"的单一接口**(实测 `GET /contact/v3/users?page_size=1` 返回空)。

~~**标准等价路径:** `GET /contact/v3/users/find_by_department?department_id=0&user_id_type=open_id&page_size=50`,从根部门(`department_id=0`)拉出所有用户。~~ **错误:** 该路径只拉到根部门**直属**用户,**不递归**(§9.5 实测确认 `fetch_child` 参数在该端点无效)。

**正确路径(见 §9.5):**
1. `GET /departments/0/children?fetch_child=true` 拉**部门树**(本端点 `fetch_child` **有效**)
2. 对树上**每个**部门(含根)调 `find_by_department(dept_id)` 拿其**直属**成员
3. union dedupe

配合 `has_more` + `page_token` 分页。

### 3.2 限频(rate limit)

- **本次实测未触发限频** —— 7 人租户,数十次调用均无 429,响应 header 中**未观察到 `X-Ratelimit-*` 类字段**(已 grep 验证)
- 飞书有 per-app 限频(响应里限频信息一般以错误码 99991400 返回),**具体阈值需查官方文档或在大租户实测**;敏感接口(如批量创建用户)通常更严格
- material-storage 场景:~100 人 / ~10 部门,单次全量同步预计 < 30 次 API 调用,**不大可能触及限频上限**;具体上限留待 §9 未尽事项 #4 实测

### 3.3 增量事件(通讯录相关全清单)

从 `larksuite/oapi-sdk-python` 的 `contact/v3/model` 目录(grep `p2_*`):

| 事件名 | 触发 |
| --- | --- |
| `contact.user.created_v3` | 入职 / 新加 |
| `contact.user.updated_v3` | 改名 / 换部门 / 改职级 / 改 leader 等 |
| `contact.user.deleted_v3` | 离职 |
| `contact.department.created_v3` | 建部门 |
| `contact.department.updated_v3` | 部门改名 / 改 parent |
| `contact.department.deleted_v3` | 删部门 |
| `contact.scope.updated_v3` | 应用可见范围变化(IT 改了应用 scope 设置) |
| `contact.custom_attr_event.updated_v3` | 自定义字段**定义**变更(不是值变化) |
| `contact.employee_type_enum.{created,updated,deleted,activated,deactivated}_v3` | 自定义人员类型管理 |

**缺失但常被需要的事件:**

- ❌ **用户组 (group) 成员变更**:没有事件 → 必须轮询 / 按需查 `member_belong`
- ❌ **职级 (job_level) / 职务 (job_title) / 职务序列 (job_family) 体系变更**:没有事件
- ❌ **角色 (functional_role) 成员变更**:没有事件
- ❌ **自定义字段值变化**:`custom_attr_event` 是**定义**变更(增减字段),用户身上**字段值**的变化合并在 `user.updated_v3` 里

### 3.4 推荐 freshness 方案

```
日常: contact.user.{created,updated,deleted}_v3 事件 →
       bridge 异步落 material-storage 本地缓存
对账: 每日凌晨一次 全量 (按 §9.5 正确路径:部门树 + 逐部门 find_by_department + dedupe),
       与本地缓存 diff,发现不一致写告警 + 修正
冷启动 / 重建: 全量同步即可。~100 人 / ~10 部门级别,~50 次 API 调用,
              估算 < 60s 完成(按部门树遍历 + 限频缓冲;原 §3.1 推测的 "< 30s" 基于单次
              调用,§9.5 实测确认必须遍历部门树,时间相应放宽)
```

## 4. 临时 / 外部 / 合作方账号(回答 issue Q4)

### 4.1 飞书开放平台**不暴露**"外部联系人"API

(实测) `GET /contact/v3/external_contacts` 返回 `404 page not found`。检索 `larksuite/lark-openapi-mcp` 的 contact 全 path 清单,无任何 `external_*` 端点。

飞书 IM 客户端层的"添加外部联系人"功能(用户在自己客户端加好友)**不暴露给企业自建应用**。原因推测:这是用户私域的社交关系,不属于企业通讯录。

### 4.2 飞书自身提供的"外部 / 临时账号"机制

1. **自定义 `employee_type`**:管理后台可加自定义人员类型(如"外部顾问""临时合作"),通过 `contact/v3/employee_type_enums` 创建。这些"外部"成员仍**进通讯录**,占企业人数,有完整 open_id + 状态机。**适合长期外包/驻场,不适合一次性合作方**。
2. **访客账号(我方推断,非飞书官方术语)**:把短期合作方邀请进飞书企业,IT 标记自定义 employee_type,合作结束后标 `is_resigned=true`。
3. **外部联系人(管理后台 → 外部群组)**:有"外部联系人 ID",但需要双方都是飞书用户,且对方主动同意,**适合 B2B 协作,不适合 material-storage 的临时下载授权**

### 4.3 对 material-storage 的影响(差距点)

- **核心员工的 SoT 走飞书,可行** ✅
- **外部合作方走飞书,有摩擦** ⚠️:每个外部合作方都要 IT 在飞书企业建账号(占名额),material-storage 不能"直接给一个 email/手机号发个临时下载 URL"
- **替代方案:** material-storage 自维护一张"临时账号 / 邮箱白名单"表,与飞书 SoT 完全解耦。临时账号不参与飞书审批,走另一条"邮箱 OTP + 一次性下载链接"路径。**这是 material-storage agent 的设计决策点,本调研只指出存在缺口。**

## 5. 权限范围 (scope) + token 类型差异(回答 issue Q5)

### 5.1 关键 scope 一览(对 material-storage 场景)

| Scope | 用途 | 必需性(对 SoT 场景) |
| --- | --- | --- |
| `contact:contact:readonly_as_app` | 应用身份读通讯录(用户/部门基本字段) | **必须** |
| `contact:user.base:readonly` | 用户基本字段(open_id, name, avatar) | 通常默认包含 |
| `contact:user.employee:readonly` | 受雇信息(employee_no, employee_type, join_time, enterprise_email) | **必须**(决定能否拿入职时间) |
| `contact:user.employee_id:readonly` | `user_id` 字段 | 可选(我方推荐用 open_id) |
| `contact:user.email:readonly` | `email` 字段 | **必须**(若用邮箱做业务用户名) |
| `contact:user.phone:readonly` | `mobile` 字段 | 可选(短信通知场景) |
| `contact:job_family` / `:readonly` | 职务序列 | 可选 |
| `contact:job_level` / `:readonly` | 职级 | 推荐(权限映射维度) |
| `contact:custom_attr.tenant:readonly` | 自定义字段 | 视租户而定 |

### 5.2 `tenant_access_token` vs `user_access_token` 字段差异

(实测 + 文档 [`refs/feshu/auth2.md`](../../../../refs/feshu/auth2.md))

| 字段 | `tenant_access_token` 单查 | `user_access_token` (`/authen/v1/user_info`) |
| --- | --- | --- |
| `open_id` / `union_id` / `name` / `en_name` / `avatar_*` | ✓ 默认 | ✓ |
| `email` / `mobile` | **默认为空,需 IT 后台显式授权应用读取或走 user_access_token** | 用户授权后可见(scope 必申请) |
| `enterprise_email` | **默认为空,需 IT 后台显式授权应用读取或走 user_access_token** | 同 |
| `employee_no` / `employee_type` / `join_time` | ✓ | ✓ |
| `user_id` | ✓ | ✓(若申请 `:employee_id:readonly`) |
| `is_tenant_manager` | ✓ | (未明确,通常用户视角不返回) |
| `mobile_visible` | ✓ true | n/a |
| `is_resigned` 等 status | ✓(SDK + 推论;实测未直接验证,见 §2.1 caveat) | **❌ 离职后整体 20021 错误,字段不可达** |

**重要规律:** `mobile` / `email` / `enterprise_email` 在 `tenant_access_token` 下**默认为空,需 IT 后台显式授权应用读取或走 user_access_token**。这是飞书的"用户隐私优先"设计。

### 5.3 对 bridge 的影响

- bridge 用 `tenant_access_token` 做"应用身份"调通讯录,拿核心字段足够
- 若 material-storage 需要邮箱做用户名:**两条路**
  - (a) IT 在飞书后台显式授权应用读取邮箱字段
  - (b) 走 OAuth(MS-FB-004 SSO)拿 `user_access_token`,首次登录时读用户邮箱并落库

## 6. material-storage 本地仍要维护什么(回答 issue Q6,差距分析)

假设通讯录作 SoT,bridge 把以下字段通过 MS-FB-002 暴露给 material-storage:

`open_id` / `union_id` / `name` / `email`(若可见)/ `department_ids[]` / `primary_dept_id` / `job_level_id` / `is_resigned` / `is_frozen` / `mobile`(若可见)/ `custom_attrs[]`

material-storage **本地还必须自维护**的字段(SoT 不能完全替代):

| 本地字段 | 为何不能从飞书取 |
| --- | --- |
| **material-storage 内部 user_id**(数据库主键) | 应用自身的稳定主键,与飞书 open_id 解耦,便于换 IM 平台 |
| **角色 → 资源类别绑定**(business mapping) | 飞书职级是数字,业务"资源类别"是 material-storage 的领域概念,二者映射在本地 |
| **审批人路由规则**(approval routing,见 MS-FB-005) | 飞书的 leader_user_id 只是直接主管,业务"该类资源谁审"的规则与组织架构不严格等同 |
| **下载配额 / 速率限制**(per-user policy) | material-storage 业务策略 |
| **审计日志**(谁下了什么,什么时候) | material-storage 内部数据 |
| **临时账号 / 外部合作方账号**(见 §4) | 飞书不暴露,必须本地维护 |
| **自定义业务标签**(资源类别偏好、AB 实验组等) | 不属于通讯录字段范畴 |

**判断:** 通讯录作 SoT,**material-storage 本地维护的字段量约 30-50% 的用户表大小**(主要是业务策略 + 审计 + 外部账号),不算"通讯录假 SoT"。LDAP/AD 的本地维护量也类似(LDAP 也只是同步 IT 数据,业务策略本地存),所以**走飞书 SoT 不会显著增加 material-storage 本地复杂度**。

## 7. 多账号 / 主子账号 / 多组织(回答 issue Q7)

### 7.1 `open_id` 跨组织的边界

- `open_id` 是 **"应用 × 用户"** 的笛卡尔积下的唯一标识
- material-storage 的飞书应用 = `cli_aa8c58fae5391be7`,绑定企业 = 我方租户。`/contact/v3/*` 接口都是**当前 tenant 视角**:返回的所有用户、部门、open_id 都属于本租户
- **不会拿回多组织数据**:即使某员工在飞书加入了多个企业(我方 + 客户公司),通过我方应用的 `tenant_access_token` 调 API,**只能看到该员工在我方租户的身份**;同一员工在客户公司的身份是另一组 open_id,我方无感

### 7.2 union_id 的作用与边界

- `union_id` 跨 **同一开发者(ISV)的多个应用**:同一个用户对一个开发者的所有应用 `union_id` 一致
- material-storage 单应用场景下,`union_id` ≈ `open_id`(信息冗余,但稳定)
- **若日后增加 feishu-integration 之外的飞书应用**(例如做一个内部 BI 应用),用户在两个应用的 open_id 不同,但 union_id 相同。这是后续扩展的一道保险绳

### 7.3 建议

- 短期(单应用):material-storage 内部主键存 **`open_id` + `union_id` 同时备份**;查询索引用 `open_id`
- 长期:若新增飞书应用,可以在保留 `open_id` 的同时,以 `union_id` 做"同一人在多应用聚合"

## 8. 结论与推荐

### 8.1 直接回答 issue 的核心问题:能不能用飞书通讯录作 SoT?

**可以,推荐采纳,但加 3 条边界 + 1 条 caveat:**

1. **核心员工身份(姓名 / 部门 / 职级 / 入职 / 离职)** 完整满足。事件订阅 + 全量对账兜底,**离职闭环高可信**,这是 SoT 的核心 SLA。
2. **外部合作方账号**不能完全靠飞书 —— **要么把外部方建进飞书企业自定义 employee_type**(IT 多一道流程),**要么 material-storage 自维护一张外部账号表**。本调研建议后者(简单 + 不污染飞书企业人数)
3. **`mobile` / `email` 等敏感字段** 在 `tenant_access_token` 下默认返回空。落地前 IT 在飞书后台明确授权应用读取,或走 OAuth 用 `user_access_token` 拿

⚠️ **未实测 caveat:** 离职后 `tenant_access_token` 下 `GET /contact/v3/users/:id` 是否仍返回完整记录(只是 `status.is_resigned=true`),**未直接实测**。结论建立在两条间接证据:(a) SDK `user_event.py` 把 `is_resigned` 列为常规字段,(b) OAuth `user_access_token` 路径离职后 20021 与 `/contact/v3/*` 是分离的两套接口。**Material-storage 接入 PoC 阶段需要做一次实测把这条 caveat 关掉**(见 §9 未尽事项 #1)。若实测发现离职后 GET 返回 404 或字段不完整,需要调整 bridge 内部缓存策略 —— 但**不影响**本调研"飞书 SoT 可行"的整体结论(只是细节调整)。

### 8.2 与原方案 (LDAP/AD) 的对比

| 维度 | LDAP/AD | 飞书通讯录 SoT |
| --- | --- | --- |
| 部署 / 维护成本 | 需 IT 部署 / 备份 / 高可用 | 无,飞书托管 |
| 字段集合 | LDAP schema 灵活但 IT 要建 | 飞书 schema 固定,够用 |
| 事件订阅 | 标准 LDAP 不暴露事件,要业务侧轮询 | 用户事件齐全(`*_v3`)|
| 离职闭环 | 看 LDAP `inetOrgPerson.employeeNumber` 等手动维护字段 | `is_resigned` 直接暴露 + 事件 + `old_object` |
| 多部门归属 | LDAP `memberOf` 支持 | `department_ids[]` 原生 |
| 外部 / 临时账号 | 自建轻松(LDAP 一条记录) | **不直接支持**(差距 §4) |
| 跨组织 | 不涉及 | union_id 已设计 |
| 与审批联动 | 解耦 | 同一应用,自然联动 |

**采纳飞书 SoT 路径的净收益:** 砍掉 LDAP/AD 整层运维,IT 投入显著下降;唯一明显代价是外部账号场景需要 material-storage 自管(也不是大事)。

### 8.3 对契约 MS-FB-002 的输入

bridge 暴露给 material-storage 的"身份解析"接口(MS-FB-002),建议字段集合(`?` 表示在某些 scope / IT 后台授权配置下可能为空;**具体 nullable 语义由 MS-FB-002 契约文档定义**,本节只给字段范围):

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
    last_synced_at                          // bridge 本地缓存时间戳
}
```

`POST /v1/users/by-email`(scope 内)、`POST /v1/users/batch_get_id`(手机/邮箱反查批量)作为辅助。

bridge 内部用"事件订阅 + 全量对账"模式维护本地缓存,upstream 查询时直接读缓存即可。

## 9. 未尽事项 / 待实测

| # | 事项 | 影响 | 状态 |
| --- | --- | --- | --- |
| 1 | 实测离职用户的 `GET /users/:id` 行为(本租户无离职用户) | 验证 `is_resigned=true` 后仍可读 | ⏳ 待造测试用户走离职;或永久 caveat |
| 2 | 实测 `mobile` / `email` 在 IT 后台开放字段权限后的真实返回 | 决定 MS-FB-002 contract 中这两个字段标 `nullable` 还是 `required` | ⏳ 待 IT 开 scope |
| 3 | 实测自定义字段 (`custom_attrs`) 配置后的读取格式 | MS-FB-002 是否要把 custom_attrs 透传 | ⏳ 待 IT 配字段 |
| 4 | 实测大租户(> 1000 人)的全量同步耗时 + 限频触发阈值 | 决定全量频率(每日 vs 每周) | ⏳ 留生产环境 |
| ~~5~~ | ~~`find_by_department(fetch_child=true)` 一次性递归?~~ | — | ✅ **已实测(2026-05-16),结论:** `fetch_child` 参数对本端点**无效**,见 §9.5 |
| ~~6~~ | ~~`functional_roles` 无 LIST work-around~~ | — | ✅ **已调研(2026-05-16),结论:** 比预期更严,见 §9.6 |
| 7 | `open_id` 跨应用域机制深度确认 | 验证机制(union_id 反查 / user_id 检索 / 其他) | 🔴 需要第二个应用,本租户单应用永久 caveat。**对 MS-FB-004 影响:** [`sso.md`](../contracts/sso.md) `sub = union_id` 的稳定性依赖 **"同一开发者多应用 union_id 稳定"** 这一飞书文档承诺,与 #7 是**同族**无法实测问题(同一原因:单应用)。**v1 contract 依赖飞书文档承诺,未来增第二应用时优先验** |

这些不阻塞结论,落地实施(MS-FB-002 实施 + bridge 通讯录缓存层)时补即可。

### 9.5 #5 实测结果:`find_by_department` 的 `fetch_child` 参数对用户端点**无效**

**测试环境:** 测试应用 `cli_aa8c58fae5391be7`,租户 7 人,部门结构 = 根(0)→ 研发部 → {后端, 前端}。

**测试方法:** 同一参数集只变 `fetch_child` true/false,比较返回 user 数量。

| 调用 | 结果 |
| --- | --- |
| `GET /contact/v3/users/find_by_department?department_id=0&fetch_child=false` | 5 用户(根部门直属) |
| `GET /contact/v3/users/find_by_department?department_id=0&fetch_child=true` | **5 用户(同样,不递归)** |
| 逐子部门遍历 dept_id ∈ {0, 研发部, 后端, 前端} 后 dedupe | 7 用户 ✓ |

**结论:** `fetch_child` 参数飞书 server 直接忽略(无报错);[官方 Zod schema](https://github.com/larksuite/lark-openapi-mcp/blob/main/src/mcp-tool/tools/zh/gen-tools/zod/contact_v3.ts) **明示**该端点参数表里**没有** `fetch_child`,接口描述本身就叫"获取部门**直属**用户列表"。

**这与本文档之前 §3.1 推测"`fetch_child=true` 一次性递归"不符,修正:**

> **bridge 全量同步必须遍历部门树**:
> 1. `GET /departments/0/children?fetch_child=true` 拉部门树(本端点 `fetch_child` **有效**)
> 2. 对树上每个部门(含根)调 `find_by_department(dept_id)` 拿其直属成员
> 3. union dedupe

100 人级租户,部门数通常 < 50,全量同步 API 调用次数 ~50,远低于限频。已在 §3.4 推荐方案中体现,无需调整。

### 9.6 #6 `functional_roles` API 严重 limitation(比预期更严)

**事实(基于 [contact_v3.ts](https://github.com/larksuite/lark-openapi-mcp/blob/main/src/mcp-tool/tools/zh/gen-tools/zod/contact_v3.ts) 全 path 清单 + SDK p2_* 事件文件清单):**

`functional_roles` namespace 完整接口集合:

| Endpoint | 方法 | 用途 |
| --- | --- | --- |
| `/contact/v3/functional_roles` | POST | 创建角色 |
| `/contact/v3/functional_roles/:role_id` | DELETE | 删除角色 |
| `/contact/v3/functional_roles/:role_id` | PUT | 改角色名(注:仅 name,无 metadata 编辑)|
| `/contact/v3/functional_roles/:role_id/members/batch_create` | POST | 批量加成员 |
| `/contact/v3/functional_roles/:role_id/members/batch_delete` | PATCH | 批量删成员(飞书 API 选 PATCH 非 DELETE,**已 verify 非笔误**) |
| `/contact/v3/functional_roles/:role_id/members/:member_id` | GET | 查某成员 |
| `/contact/v3/functional_roles/:role_id/members` | GET | 列角色成员 |
| `/contact/v3/functional_roles/:role_id/members/scopes` | PATCH | 改成员的 scope |

**关键 limitation(比 §1.1 表中先前判断"无 LIST"更严):**

1. **无 `GET /functional_roles`**(无 LIST 所有角色)— 应用无法发现已有 role 集合
2. **无 `GET /functional_roles/:role_id`**(无 GET 单个角色 metadata)— **即使应用预知 role_id**,也**只能查成员,查不到 role 自身的 name / 创建时间 / 配置**
3. **无 functional_role.* 事件订阅**(SDK `contact/v3/model` 目录下没有 `p2_contact_functional_role_*_v3.py`)— 不能"通过事件订阅自建本地 role_id 表"

**Work-around 现实方案:**

| 路径 | 描述 | ownership / 优缺点 |
| --- | --- | --- |
| (A) **手工配 `role_id → role_name` 映射** | 配置文件 / env / DB 维护 | **ownership 需 MS-FB-005 起草时拍**:bridge 维护(通过 MS-FB-005 contract 暴露给上游)vs material-storage 维护(完全在业务策略层)— 二者皆可,影响 contract surface area;**推荐 v1 走此路**,工作量小但易过时 |
| (B) **不依赖 functional_role** | RBAC 维度改用 **部门** + **职级** + **用户组 (group)** 三件套(前两者数据全 + 事件齐;group 数据全但无事件) | 业务表达力可能不够,但 API 完备 |
| (C) **bridge 自维护 role_id 集合** | bridge 监听 user.updated_v3 事件,扫所有 user 的 role 字段(若存在) | **未实测**:本应用事件订阅未配置,无法实测 `user.updated_v3` payload 是否含 role 字段;**待事件订阅启用后再实测**,5 min 即可关此 caveat |

**对 MS-FB-002 / MS-FB-005 契约的影响:**

- MS-FB-002 v1 字段集合**不**含 functional_role 信息(已经一致;[`identity.md`](../contracts/identity.md) §"v1 不暴露的字段"已预排 `functional_role` / `job_family` 待 MS-FB-005 演进)
- MS-FB-005 审批人路由若依赖 functional_role,**应采纳 (A) 路径或回到 (B) 路径**;不要假设 bridge 能自动同步全 role 集合

实施时应**新开 feishu ADR(RBAC 主轴)或 MS-FB-005 contract (planned, 尚未起草) 起草前**显式拍板 ownership (A) 路径归 bridge 还是 material-storage。**本次研究已经做完;结论:`functional_roles` 不适合作 RBAC 主轴**。

## 10. 参考文档

| 标题 | URL |
| --- | --- |
| 通讯录概述 | <https://open.feishu.cn/document/server-docs/contact-v3/contact-overview> |
| 获取单个用户信息 | <https://open.feishu.cn/document/server-docs/contact-v3/user/get> |
| 获取部门直属用户列表 (`find_by_department`) | <https://open.feishu.cn/document/server-docs/contact-v3/user/find_by_department> |
| 通讯录权限 | <https://open.feishu.cn/document/server-docs/contact-v3/permissions> |
| `contact.user.deleted_v3` 事件 | <https://open.feishu.cn/document/server-docs/contact-v3/user/events/deleted> |
| `contact.user.created_v3` 事件 | <https://open.feishu.cn/document/server-docs/contact-v3/user/events/created> |
| 自建应用获取 `tenant_access_token` | <https://open.feishu.cn/document/server-docs/authentication-management/access-token/tenant_access_token_internal> |
| 用户身份 ID 介绍(open_id/union_id/user_id) | <https://open.feishu.cn/document/server-docs/contact-v3/contact-overview-faq> |
| `larksuite/oapi-sdk-python` contact 模型(本调研字段集合的主要证据) | <https://github.com/larksuite/oapi-sdk-python/tree/main/lark_oapi/api/contact/v3/model> |
| `larksuite/lark-openapi-mcp` contact_v3 Zod schemas(本调研 path 清单的主要证据) | <https://github.com/larksuite/lark-openapi-mcp/blob/main/src/mcp-tool/tools/zh/gen-tools/zod/contact_v3.ts> |
