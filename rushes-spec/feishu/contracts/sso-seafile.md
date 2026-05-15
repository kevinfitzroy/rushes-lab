# Contract: Seafile 作为 OIDC RP 接入 bridge (sso-seafile) v1

## 能力描述

定义 **Seafile**(CE / Pro)作为 OAuth2 / OIDC Relying Party 接入 `feishu-integration`(下称 **bridge**)的 OIDC provider 时的完整集成约定。Seafile 本身的 OAuth2 backend 不是完整 OIDC client(不验证 `id_token` / 不取 discovery / 不取 JWKS),只 hit bridge 的 `userinfo` endpoint —— 因此本契约**重点冻结 userinfo response 形状 + Seafile 侧 `seahub_settings.py` 配置 + 用户身份映射规则**。

**覆盖需求:** [issue #24](https://github.com/kevinfitzroy/rushes-lab/issues/24) WP1(MS-FB-006)。

**不覆盖:** WP2 下载审批桥接(独立契约 [`approval-seafile.md`](./approval-seafile.md) / MS-FB-007)、通用 SSO OIDC 协议本身(由 MS-FB-004 通用 SSO 契约定义,待起草)。

**调研依据:**
- 飞书 ADR-0002: [`../decisions/0002-bridge-as-oidc-provider.md`](../decisions/0002-bridge-as-oidc-provider.md)
- 飞书 MS-FB-002: [`./identity.md`](./identity.md)(身份字段集合)
- material-storage ADR-0002: [`../../material-storage/decisions/0002-feishu-contacts-as-identity-source.md`](../../material-storage/decisions/0002-feishu-contacts-as-identity-source.md)
- Seafile 官方文档 [`oauth.md`](https://github.com/haiwen/seafile-admin-docs/blob/master/manual/config/oauth.md)
- Seafile 源码 [`seahub/oauth/views.py`](https://github.com/haiwen/seahub/blob/master/seahub/oauth/views.py)(认证回调实现)

## 版本

- **当前版本:** v1
- **状态:** draft
- **变更日志:**
  - 2026-05-15: initial draft (feishu agent)

## 1. 关键事实(Seafile OAuth2 backend 行为)

| 事实 | 来源 | 影响 |
| --- | --- | --- |
| Seafile **不**是完整 OIDC client。不取 discovery、不验证 `id_token`、不取 JWKS | `oauth/views.py` 实现 | bridge 的 OIDC discovery / JWKS endpoints **对 Seafile 不发挥作用**(但仍要暴露,服务 oCIS 等未来 OIDC-only RP 与符合 OIDC 标准) |
| Seafile **只** GET `OAUTH_USER_INFO_URL`,用 access_token 拿 JSON userinfo,按 `OAUTH_ATTRIBUTE_MAP` 抽字段 | `views.py` L157-177 | bridge `/oidc/userinfo` 是**关键接口**,必须返回 Seafile 期望的 claim |
| Seafile 11.0+ 用 `uid` 作"外部唯一标识"(在 `social_auth_usersocialauth` 表),`email` 作"Seafile 用户主键 (username)" | `views.py` L183-228;`oauth.md` "OAUTH_ATTRIBUTE_MAP" 节 | bridge `sub` = `union_id` 映射到 Seafile `uid`;Seafile 用 email 作 username |
| 若 userinfo `email` 是非空但非邮箱格式,Seafile 会拼成 `{email}@{OAUTH_PROVIDER}` 当 username(11.0 之前路径) | `views.py` L200-208 | 我方新部署 + email scope,正常路径下走不到 |
| 若 userinfo `email` 为 `null`,Seafile 调 `OauthRemoteUserBackend.authenticate(remote_user=None)` → 命中 `create_unknown_user=True` 分支 → 调 `User.objects.create_oauth_user()` → 内部 `gen_user_virtual_id()` 生成一个**虚拟 ID**(内部字符串,**非邮箱格式**)作 username | `oauth/backends.py` + `base/accounts.py` `create_oauth_user` | 当 `email` claim 为 `null`(MS-FB-002 §"字段 null 语义"允许),Seafile 用户的 `username` = 一串 virtual_id(用户视角不可读);`contact_email` = `null`。**首次登录后该用户的 SocialAuthUser 表绑定 `provider=feishu, uid=<union_id>, username=<virtual_id>`,后续登录命中**(不依赖 email)|
| `OAUTH_PROVIDER` 是命名空间字符串,可任意 ≤32 字符 | `oauth.md` "OAUTH_PROVIDER" 节 | 我方约定固定为 `feishu`,见 §3 |
| 首次登录自动建用户由 `OAUTH_CREATE_UNKNOWN_USER` 控制(默认 `True`)| `oauth.md` | 我方约定 `True`,见 §3 |

## 2. bridge 侧 userinfo response 形状(冻结)

`GET https://<bridge-issuer>/oidc/userinfo` with `Authorization: Bearer <oidc_access_token>` 返回 200 JSON:

| Claim | 类型 | 必返 | 含义 / 来源(参考 ADR-0002 §"JWT claims ↔ 飞书字段映射") |
| --- | --- | --- | --- |
| `sub` | string | ✓ | **飞书 `union_id`**(ISV 作用域稳定;Seafile 把它存进 `uid` 列) |
| `name` | string | ✓ | 飞书 `user.name` |
| `email` | string \| null | ✓ 字段必有,值可 `null` | 飞书 `user.email` 或 `enterprise_email`,详见 MS-FB-002 §"字段 null 语义"。值为 `null` 时 Seafile fallback 到 `{sub}@feishu` |
| `preferred_username` | string | ✓ | `email` 非空时取 `email`;否则取 `name` |
| `feishu_open_id` | string | ✓ | 飞书 bridge 应用域下的 `open_id`,供 Seafile 透传到 material-storage 做审计 / 关联 |
| `groups` | array of string | ✓(可空数组) | 飞书 `department_chain[].open_department_id` 数组;Seafile 不内置 group→role 映射,字段保留供 material-storage 业务策略层消费 |

> **Seafile 不消费 `feishu_open_id` 和 `groups`**(`OAUTH_ATTRIBUTE_MAP` 不映射),但 bridge 仍返回,统一 RP 视图(oCIS / 其他底座可能用)。

## 3. Seafile `seahub_settings.py` 冻结配置

> 部署运维参考。具体 `OAUTH_*` 字面值由 IT 在 Seafile 服务器 `conf/seahub_settings.py` 写入。

```python
ENABLE_OAUTH = True

# 首次登录自动建账号 + 激活(material-storage ADR-0002 JIT provisioning 路径)
OAUTH_CREATE_UNKNOWN_USER = True
OAUTH_ACTIVATE_USER_AFTER_CREATION = True

# bridge OIDC 端点(具体 issuer URL 见 §4)
OAUTH_PROVIDER = 'feishu'
OAUTH_AUTHORIZATION_URL = '<BRIDGE_ISSUER>/oidc/authorize'
OAUTH_TOKEN_URL         = '<BRIDGE_ISSUER>/oidc/token'
OAUTH_USER_INFO_URL     = '<BRIDGE_ISSUER>/oidc/userinfo'

# OAuth2 client 凭证(bridge 静态客户端配置,见 ADR-0002 §3)
OAUTH_CLIENT_ID     = 'seafile-prod'
OAUTH_CLIENT_SECRET = '<from env, 不入仓库>'

# 回调 URL(注册到 bridge 的 redirect_uri 白名单,见 §5)
OAUTH_REDIRECT_URL = '<SEAFILE_BASE_URL>/oauth/callback/'

# OIDC 标准 scope。bridge 仅识别 `openid` 必填;其他 scope 是 OIDC 惯例
OAUTH_SCOPE = ['openid', 'profile', 'email']

# Claim → Seafile 字段映射(11.0+ 标准 schema,见 §1 关键事实第 3 条)
OAUTH_ATTRIBUTE_MAP = {
    'sub':   (True,  'uid'),            # 关键:union_id → Seafile uid
    'name':  (False, 'name'),
    'email': (False, 'contact_email'),
}

# 生产**必为 False**(强制 HTTPS)。仅本机 PoC 阶段(`bridge_issuer` 是 http://localhost...)可
# 临时设 True,production 务必关闭。bridge 默认强制 HTTPS,设 True 仅影响 Seafile 端 lib 校验。
OAUTH_ENABLE_INSECURE_TRANSPORT = False
```

> **不**配 `OAUTH_PROVIDER_DOMAIN`(已 deprecated,见 `oauth.md`)。
> **不**配 `id: (True, email)` 兼容项 —— 我方是新部署 11.0+ Seafile,无 < 11.0 老用户。

## 4. bridge 配置(对应)

| env | 值 | 说明 |
| --- | --- | --- |
| `OIDC_ISSUER` | 业务域名形如 `https://id.<company>.com/oidc`(测试服 `https://rusheslab.taoxiplan.com/oidc`)| ADR-0002 review 补建议:**`iss` 一旦定下不可轻易变**(已签 token / discovery cache 全部依赖) |
| `OIDC_CLIENTS[seafile-prod].client_secret` | 高熵随机(≥ 32 字符) | 与 Seafile `OAUTH_CLIENT_SECRET` 一致;**不入 git**,走 env / vault |
| `OIDC_CLIENTS[seafile-prod].redirect_uris` | `["https://<seafile-host>/oauth/callback/"]` | 必须**字面相等**于 Seafile 配置的 `OAUTH_REDIRECT_URL`(OIDC 标准:redirect_uri 严格匹配,不允许 wildcard) |

## 5. 身份映射时序与边界

### 5.1 首次登录(JIT provisioning)

```
1. 用户访问 Seafile,点 "Login with feishu"(或 Seafile 首页 OAuth 按钮)
2. Seafile 重定向到 bridge /oidc/authorize?...&state=...&scope=openid profile email
3. bridge 持久化 state,重定向到飞书 /authen/v1/index
4. 用户在飞书 OAuth 授权,回调 bridge /login/callback?code=...
5. bridge:换 user_access_token → /authen/v1/user_info → 拿 open_id / union_id / name / email
   → 落 MS-FB-002 缓存 → bridge 签 authorization_code 重定向回 Seafile redirect_uri
6. Seafile POST bridge /oidc/token → bridge 返回 {access_token, id_token, refresh_token}
   (Seafile 仅消费 access_token,id_token 不验证)
7. Seafile GET bridge /oidc/userinfo with access_token → 返回 §2 schema
8. Seafile 按 OAUTH_ATTRIBUTE_MAP 抽 sub/name/email
9. Seafile 查 SocialAuthUser by (provider='feishu', uid=<sub/union_id>)
   - 命中:走 step 10
   - 未命中:**建新 Seafile user**:
     - 若 email 是合法邮箱:username = email,contact_email = email
     - 若 email 为 null:走 `create_oauth_user()` 路径,**username = gen_user_virtual_id() 内部虚拟 ID**(非邮箱格式,用户视角不可读),contact_email = null
     - 任一情况下:`SocialAuthUser.add(username, 'feishu', sub)` 绑定 union_id ↔ username
10. Seafile session 建立
```

### 5.2 后续登录

step 9 命中 SocialAuthUser → 跳到 step 10,**username (即 Seafile 主键 email) 不变**,即使飞书侧 `name` / `email` 字段更新,Seafile **不主动同步**(`contact_email` 字段会被覆盖,见 `views.py` 中 `OAUTH_ATTRIBUTE_MAP` 处理逻辑)。

### 5.3 关键边界 case

| 场景 | 行为 |
| --- | --- |
| 飞书侧用户离职(`status.is_resigned=true`) | 飞书 OAuth `/authen/v1/user_info` 返回 20021(见 MS-FB-002 §字段 null 语义)→ bridge `/oidc/authorize` step 5 失败 → Seafile 收到 OAuth 错误,**用户登录被拒**。**Seafile 本地账号不主动禁用,但无法登录** —— 这是隐式禁用 |
| 飞书侧 email 后填充(用户首次走 SSO 后 IT 后台开通 email scope) | bridge userinfo `email` claim 从 `null` 变实际值;Seafile 后续登录的 **`contact_email` 字段会被更新**(`Profile.add_or_update`),但 **`username`(主键)不变**,仍是首次登录时分配的 virtual_id —— **不会自动迁移成真实邮箱**。若 IT 想"用户首次登录前未开 email scope、后续想换成邮箱主键",需要手动 `User.objects.update_email(virtual_id, real_email)` 之类的 DB 操作(Seafile 不暴露 OAuth 自动迁移路径)|
| 同一 union_id 在 Seafile 上已有 username 但**不通过 SSO 建**(IT 手工建的 admin) | step 9 未命中 SocialAuthUser → 会**新建一个新 user**,与既有 admin 同 union_id 但不同 username。**这是冲突源**。**预迁移强制步骤**(切 OAuth 之前 IT 必跑,详见 §6 上线 checklist):对每个手工建 admin 跑 `SocialAuthUser.objects.add(<admin_username>, 'feishu', <admin_union_id>)`,即把已有 admin 绑到飞书 OIDC sub;无此步骤,**首次启用 OAuth 后管理员可能登不进自己原账号** |
| 飞书重建应用导致 `open_id` 变(material-storage ADR-0002 注意点) | `sub = union_id` 不变,所以 Seafile 视角下用户身份**稳定** ✓(本契约的核心收益) |
| 用户在 Seafile 强制修改 username(管理员行为) | Seafile `username` 变,但 SocialAuthUser 表的 `uid` (union_id) 不变,下次 SSO 仍会找到同一账号 ✓ |

## 6. v1 不实现 / 未决

1. **id_token 验签** —— Seafile 不验,bridge 仍签 RS256(给未来 OIDC-only RP)。v1 不实现"Seafile 端 id_token 强制校验"
2. **OIDC `groups` claim 在 Seafile 内做权限映射** —— Seafile OAuth2 backend 不消费 `groups`;若 material-storage 要基于飞书部门做 Seafile 权限,**走 material-storage 业务策略层**(material-storage ADR-0002 §"本地维护字段")
3. **Refresh token 在 Seafile session 续约** —— Seafile session 默认 14 天,本契约 v1 假设 14 天内**不**强制 refresh(用户重新登录即可)。若 oCIS 等未来 RP 需要长 session,refresh 在 bridge 那侧仍实现(ADR-0002 §4),只是 Seafile 不主动用
4. **多 Seafile 实例**(prod / staging) —— v1 仅约定 `seafile-prod` 一组 client_id/secret;若要 staging,加 `seafile-staging` client(v1.x 演进,不影响 schema)
5. **Seafile pro 特性的额外 claim**(`is_staff` / `is_active` / 组织角色)—— v1 不映射;真有需要在 bridge userinfo 加新 claim 是 v1.x 演进(向后兼容)

## 7. 向后兼容承诺(v1 → 未来)

| 变更类型 | v1 → v1.x(允许) | v1 → v2(必要) |
| --- | --- | --- |
| 新增 userinfo claim(可选,Seafile 不映射不受影响) | ✓ | — |
| 改 `sub` 来源(从 `union_id` 改其他) | ✗ | ✓(且会让所有 Seafile 用户身份失效,见 ADR-0002 §"风险") |
| 改 `OAUTH_ATTRIBUTE_MAP` 关键映射(sub→uid / email→contact_email) | ✗ | ✓ |
| 改 `OAUTH_PROVIDER` 字符串(从 `feishu` 改) | ✗ | ✓(等同于身份失效,所有 SocialAuthUser 记录失效) |
| `OIDC_ISSUER` URL 改 | ✗ | ✓ |
| 新增 Seafile client | ✓ | — |

## 8. 与其他契约的关系

- [`identity.md`](./identity.md) (MS-FB-002):bridge 内部用同一份用户缓存为 userinfo claims 与 REST GET `/users/:open_id` 提供数据;字段语义对齐(`email` null / `status` 兜底)
- [`approval.md`](./approval.md) (MS-FB-001):未直接耦合;MS-FB-007 (`approval-seafile.md`) 才是耦合点
- [`approval-seafile.md`](./approval-seafile.md) (MS-FB-007):**依赖本契约 §3 的 OAuth flow 完成**(下载审批的 requester 身份 = SSO 登录用户的 `union_id`)
- ADR-0002(bridge 充当 OIDC provider):本契约**复用 ADR-0002 子决策 §1-3 全部内容**,不重复;仅约束 Seafile 这个具体 RP 的接入面
- MS-FB-004 通用 SSO 契约(未起草):待起草后,本契约的 §2 userinfo schema 部分应**完全等价**于 MS-FB-004 定义的 OIDC userinfo;若两者分歧,以 MS-FB-004 为准

## 9. 上线预迁移 + PoC 验收清单

### 9.1 上线预迁移(切 OAuth **之前**必跑,IT 操作)

1. [ ] 列出 Seafile 现有所有 admin / 已有用户的 `username`(Seafile DB `User` 表)
2. [ ] 对每位用户,从飞书侧拿到对应的 `union_id`(可走飞书后台 / 手工 / 或 bridge MS-FB-002 反查;若飞书侧用户未与现有 Seafile username 对齐,**先**让其用飞书登录其他系统补 SSO 缓存,**再**拿到 union_id)
3. [ ] 在 Seafile 跑 `SocialAuthUser.objects.add(<existing_username>, 'feishu', <union_id>)` 把每位现有 user 绑到 OIDC sub —— **此步骤不做,首次启用 OAuth 后管理员会无法登录自己原账号**(见 §5.3 表)
4. [ ] 验证:Seafile `SocialAuthUser` 表至少含每位现有 admin 一条 (`provider=feishu`, `uid=<…>`, `username=<existing>`)

### 9.2 PoC 验收(Seafile Pro 到位 + §9.1 完成 + §3 配置就绪后)

1. [ ] Seafile 配置 §3 全部字段,重启 seahub
2. [ ] 既有 admin 用飞书登录 → 命中 §9.1 绑定的 SocialAuthUser → 复用现有 admin 账号(无新建)
3. [ ] 新用户(从未在 Seafile 出现)用飞书登录 → 跳 bridge → 跳飞书 → 回 Seafile → 自动建本地 user
4. [ ] 验证 Seafile 自动建的 user:
   - 若飞书 email 可见:`username` = email,`contact_email` = email
   - 若飞书 email 为 null:`username` = virtual_id(内部字符串非邮箱格式),`contact_email` = null
5. [ ] `SocialAuthUser` 表 inspect:`provider='feishu'` + `uid=<union_id>` 与 username 一致
6. [ ] 第二次登录 → 直接进入,无 user 重复创建
7. [ ] 离职用户(SoT §9 实测窗口期内,或租户内有真实离职用户)→ 飞书 OAuth 拒绝 → Seafile login 失败 → Seafile 该用户 username 仍存在但无法登录
