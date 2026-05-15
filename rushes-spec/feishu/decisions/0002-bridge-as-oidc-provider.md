# ADR-0002: bridge 充当企业 micro-IdP(OIDC provider)

- **状态:** accepted
- **日期:** 2026-05-15
- **决策者:** feishu agent
- **审阅:** material-storage agent(经 PR)
- **关联:**
  - 上游决策(把 SoT 定为飞书通讯录):[`../../material-storage/decisions/0002-feishu-contacts-as-identity-source.md`](../../material-storage/decisions/0002-feishu-contacts-as-identity-source.md)(material-storage 编号空间,语义上是本 ADR 的前置)
  - 底座选型与 OIDC 要求:[`../../material-storage/research/file-management-system.md`](../../material-storage/research/file-management-system.md) §5、§9
  - 触发 issue:[#17](https://github.com/kevinfitzroy/rushes-lab/issues/17)
  - 待起草契约:`rushes-spec/feishu/contracts/sso.md`(MS-FB-004 实现)

> 编号说明:本 ADR 在 feishu agent 编号空间为 0002;material-storage ADR-0002 §"Bridge 角色范围"提到的"ADR-0003 待写"指 material-storage 侧的 cross-reference 文件(若 material-storage 后续撰写)。双方编号空间独立。

## 背景

material-storage 已定 **飞书通讯录作身份 SoT** + LDAP/AD 不部署(material-storage ADR-0002)。首批文件管理底座 PoC 包含两个候选:

- **Nextcloud (NC)**:通过 `social_login` app 接受 generic OAuth2 — OIDC 非强制
- **oCIS 7**:**严格要求 OIDC provider**(`OCIS_OIDC_ISSUER` 必填,见 [`../../material-storage/research/file-management-system.md`](../../material-storage/research/file-management-system.md) §5 & §9 docker-compose 片段)

底座本身没有"接飞书"的能力,需要 bridge 在中间。这就引出一道设计岔:bridge 充当"OAuth2 server(轻量)"还是"OIDC provider(重量)"?

## 决策

**bridge 充当企业 micro-IdP,实现 OpenID Connect 1.0 provider**。底座(NC / oCIS / Seafile / future)统一以 OIDC client 身份接 bridge;bridge 内部把飞书身份(`open_id` / `union_id` / 通讯录字段)桥接到 OIDC claims。

### 决策的因果链(显式)

```
material-storage 首批 PoC 包含 oCIS              (上游决策, file-management-system §7)
        ↓
oCIS 严格要求 OIDC provider                       (file-management-system §5)
        ↓
bridge 必须提供 OIDC discovery + id_token + JWKS  (oCIS 启动期检查)
        ↓
做 OIDC 后,NC/Seafile 等 OAuth2 客户端也可以接   (OIDC 是 OAuth2 超集,
                                                    具体兼容性待 PoC 实测)
        ↓
单实现服务所有底座 = micro-IdP 路径
```

### 决策成立的前置条件

如果 material-storage PoC 后**oCIS 被排除且确认未来不引入 OIDC-only 底座**,本 ADR **可降级**为"bridge 实现 OAuth2-only server(去掉 id_token / discovery / JWKS)"。这是另一个 ADR 的事,本 ADR 不预先讨论降级路径。

## 实现范围(端点清单,**不**列 schema)

具体 request/response schema 落在后续契约 `rushes-spec/feishu/contracts/sso.md`(MS-FB-004 实现)与 `feishu-integration/` 实施代码 README 中。本 ADR 只锚定端点存在与用途:

| 端点 | 用途 |
| --- | --- |
| `GET  /oidc/.well-known/openid-configuration` | OIDC discovery |
| `GET  /oidc/authorize` | 启动授权码流程(内部重定向到飞书 OAuth) |
| `POST /oidc/token` | 授权码 / refresh_token 换 access_token + id_token |
| `GET  /oidc/userinfo` | OIDC 标准 userinfo |
| `GET  /oidc/jwks.json` | id_token 签名公钥 |

**支持的授权类型:** Authorization Code(含 PKCE 推荐)+ Refresh Token grant。**不实现** dynamic client registration(RFC 7591)、client credentials grant、implicit flow、device code flow。

## 配套子决策

### 1. `id_token` 签名密钥管理

- **算法:** RS256(RSA-SHA256),2048 位密钥,与多数 OIDC client 默认兼容
- **存储:** 私钥文件 `/opt/feishu-poc/oidc_signing.pem`,**0600 权限,root only**,**不入 git**(扩展 `.gitignore` 模式)
- **环境变量:** `OIDC_SIGNING_KEY_PATH=/opt/feishu-poc/oidc_signing.pem`
- **轮转:** **手动按需**,不强制定期轮转;轮转时 JWKS endpoint 短期同时暴露新旧 `kid`(key id)以平滑切换。生产部署建议每 12 个月旋一次。
- **公钥:** 不需要专门管理,运行期由 bridge 从私钥推导后由 `/oidc/jwks.json` 暴露

### 2. JWT claims ↔ 飞书字段映射

| OIDC 标准 claim | 飞书来源 | 备注 |
| --- | --- | --- |
| `sub` | **`union_id`** | **关键决策:用 union_id 不用 open_id**。理由:`open_id` 是应用作用域,**如果未来重建飞书应用或拆多应用,open_id 会变,底座所有用户身份失效**;`union_id` 跨同一 ISV 的多应用稳定,作 `sub` 更耐用 |
| `iss` | `OIDC_ISSUER`(env,推荐 `https://rusheslab.taoxiplan.com/oidc`) | OIDC 标准要求 |
| `aud` | 底座的 `client_id`(静态配置,见 §3) | OIDC 标准 |
| `iat` / `exp` | 签发时刻 / 默认 1h 后过期 | id_token 短期有效;长 session 走 refresh_token |
| `name` | 飞书 `user.name` | |
| `email` | 飞书 `user.email`(若 IT 后台已授权或用户 OAuth 同意) | 可能为空,见 [`../research/contacts-as-identity-source.md`](../research/contacts-as-identity-source.md) §5 |
| `preferred_username` | `email` 优先,否则 `name` | NC 等底座用此字段做"显示名" |
| `groups` | 飞书 `department_chain[].open_department_id` 数组 | OIDC 非标准 claim,但 NC/oCIS 普遍接受用于权限映射 |
| `feishu_open_id` | 飞书 `open_id`(本应用域) | **自定义 claim**,便于底座侧透传到 material-storage 做审计 / 关联,**不**作为身份主键 |

**`sub` 用 `union_id` 是单点关键决策。** 后续若重建飞书应用,新应用 `open_id` 会变但 `union_id` 不变 → 底座侧用户身份保持稳定,不会出现"所有底座登录全部失效"的灾难。

### 3. 底座 client 注册

- **静态配置,bridge 启动时读 env 或配置文件**(具体格式留给实施)
- 每个底座 = 一组 `client_id` + `client_secret` + 允许的 `redirect_uri` 白名单
- 初期 3 个 client 名额预留: `nc-prod` / `ocis-prod` / `seafile-prod`(具体启用按 material-storage PoC 结果)
- **不实现** dynamic client registration(RFC 7591) —— 我方场景客户端数量固定,动态注册增加攻击面与无谓复杂度

### 4. Refresh token 行为

- **实现 refresh_token grant**(advisor 建议;oCIS 等底座可能依赖 refresh 维持长 session,事后补做代价大)
- 不签 JWT,**用 opaque 字符串**(UUID 或 256-bit 随机)+ bridge 内部 Redis 表持久化(`refresh:<token>` → user_open_id + client_id + 过期时间)
- 默认 **TTL 30 天**;底座侧 refresh 后 bridge 同时旋转新旧 refresh_token,旧 token 立即失效(rotation,防重放)
- **撤销:** 用户离职事件(`contact.user.deleted_v3`)触发 bridge 主动失效该用户所有未过期 refresh_token

### 5. 登录流程整体时序

```
1. 用户访问 NC/oCIS → 底座重定向到 bridge /oidc/authorize?...&state=...
2. bridge 持久化 state + client_id + redirect_uri,重定向到飞书 /authen/v1/index
3. 用户在飞书完成 OAuth → 飞书重定向回 bridge /login/callback?code=...
4. bridge 用 code 换 user_access_token(飞书 /authen/v1/access_token)
5. bridge 用 user_access_token 拉用户信息(/authen/v1/user_info)
6. bridge 把用户信息缓存(MS-FB-002 缓存层),拿到 open_id / union_id / 必要字段
7. bridge 生成 authorization_code(自定义短期 opaque),映射到 user + client_id
8. bridge 重定向回底座 redirect_uri?code=<bridge_code>&state=<原 state>
9. 底座 POST /oidc/token,bridge 校验 client_secret,签发 id_token + access_token + refresh_token
10. 底座 GET /oidc/userinfo,bridge 用 access_token 校验后返回 claims
```

时序细节、错误码、PKCE 实现等落 MS-FB-004 契约。

## 备选方案与拒绝理由

### A. 轻量(bridge 实现 OAuth2-only,不做 OIDC)

- bridge 暴露 `/oauth/authorize` + `/oauth/token` + `/oauth/userinfo`,**不**签 id_token、**不**暴露 discovery / JWKS
- NC `social_login` app 支持;Seafile 自带 generic OAuth2 client 支持
- **拒绝**:**oCIS 必须 OIDC,排除 oCIS 等同于让 material-storage 把 oCIS 从首批 PoC 拿掉,违背 material-storage 已有 PoC 决策**。即使先轻量、后期再升 OIDC,token 签名机制要从 opaque 改 JWT,等于重做,无收益

### B. 复用现成开源 IdP(Keycloak / Authentik / Authelia)

- 部署一个 Keycloak,配置"飞书"为 federated identity provider,底座以 OIDC client 接 Keycloak
- **拒绝**:
  - Keycloak 没有内置飞书 IdP 适配器(它内置的是 Google / GitHub / Microsoft 等),要么自己写 federation provider plugin(Java),要么用 `Custom OIDC Provider` 类型 + 飞书"伪装"成 OIDC(飞书本身不是 OIDC,而是它自家 OAuth2 + 自定义 userinfo path)。两条都比 bridge 自己实现 OIDC 5 个端点工作量更大
  - 引入 Keycloak 等于运维多一个 Java 服务 + 多一份数据库,与 ADR-0001 上游决策"砍掉运维负担"精神冲突
  - 飞书事件订阅 / 审批 / IM 推送等业务能力仍要 bridge 实现,Keycloak 只解决"身份"一面,**没有给 bridge 减少代码**

### C. NC 用 OAuth2、oCIS 自己装 Keycloak / Dex(混合)

- NC 接 bridge OAuth2,oCIS 接独立 Dex,Dex 配置 bridge 为 upstream OIDC
- **拒绝**:两个身份层叠加,运维 + 调试复杂度↑,无明显好处

### D. bridge 实现完整 OIDC provider(**本决策方向**)

- **接受**

## 影响

### 对 `feishu-integration/` 实施

- 新增模块 `app/oidc/`(authorize / token / userinfo / jwks / discovery)
- 引入依赖:`PyJWT` + `cryptography`(后者已在 `requirements.txt`)
- 新增 env: `OIDC_ISSUER` / `OIDC_SIGNING_KEY_PATH` / `OIDC_CLIENTS_CONFIG_PATH`
- 新增 systemd 启动依赖检查:私钥文件存在 + 可读

### 对 Caddyfile / 路由

- bridge 的 OIDC 端点路径 `/oidc/*` 与现有 `/api/lark/callback` / `/login/callback` / `/healthz` 不冲突,Caddy 反代规则无变化

### 对契约

- MS-FB-004 SSO 契约**直接对应 OIDC 流程**,不再是简单的 "OAuth code 换 token" 描述
- 契约文档应明示:bridge 暴露的对内 SSO 接口 = 标准 OIDC 端点,不是自定义 path

### 对 material-storage

- material-storage agent 在 review 本 ADR 时,**确认 oCIS 仍在 PoC 范围**(本 ADR 的前置条件)
- material-storage 后续可考虑写自己的 ADR-0003 引用本 ADR(可选,看其内部 ADR 纪律)

## 风险与待跟踪事项

- **OIDC 兼容性 PoC 待做**:NC `social_login` app / oCIS 7 / Seafile 接 bridge OIDC 的具体兼容性需 PoC 实测。预期可行(OIDC 是标准),但各底座可能有怪癖(token endpoint 接受 form 还是 JSON、userinfo POST 还是 GET、自定义 claim 是否被解析等),需在 material-storage PoC 阶段验证
- **`sub = union_id` 的回归代价**:若决策日后翻转改用 `open_id`,所有底座上的本地用户身份会全部失效,需要重新登录 + 可能需要 admin 干预重建账号映射。此风险被显式接受 —— `union_id` 才是稳定选择
- **签名密钥泄漏:** 私钥若泄漏,攻击者可签任何用户的 id_token 冒充。缓解:文件权限 0600 / 私钥不进 git / 服务器配置标准化(SSH key only,不开放公网管理)
- **Refresh token 不旋转的窗口:** rotation 实现错误可能导致旧 refresh_token 仍能换 token。落实施时强制集成测试:旧 refresh 失效 + 新 refresh 可用
- **JWKS rotation 期间双 `kid` 共存**:实施时配置文件应支持同时配 2 个 kid(active + retired);transition 期间 client 缓存的 jwks 不会立即失效

## 变更日志

- 2026-05-15: 初版,accepted。
