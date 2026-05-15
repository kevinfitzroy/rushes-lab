# Contract: SSO (OIDC provider, sso) v1

## 能力描述

定义 `feishu-integration`(下称 **bridge**)对所有下游 OIDC Relying Party(RP)暴露的 OpenID Connect 1.0 provider 端点契约。落地 [ADR-0002 `bridge-as-oidc-provider`](../decisions/0002-bridge-as-oidc-provider.md) 的"端点 schema 与具体 request/response 形状"维度。

**适用 RP:** 所有具备标准 OIDC client 能力的下游底座 —— Seafile(具体接入约定见 [MS-FB-006 `sso-seafile.md`](./sso-seafile.md))、未来的 oCIS / NC OIDC / 其他底座。

**覆盖需求:** [issue #17](https://github.com/kevinfitzroy/rushes-lab/issues/17) P0 "MS-FB-004 飞书 SSO 契约"。

**不覆盖:**
- bridge **内部**飞书 OAuth flow(用户视角 OAuth → 飞书 → bridge 拿 user_access_token / open_id 那一段)—— 不属于 RP 接口面
- 单个具体 RP 的接入约定(Seafile 等),走单独 RP-specific 契约(`sso-seafile.md`)
- 签名密钥 / claims 映射等已在 ADR-0002 冻结的子决策 —— **本契约不重复**;仅引用

**依据:**
- [`../decisions/0002-bridge-as-oidc-provider.md`](../decisions/0002-bridge-as-oidc-provider.md):决策 + 子决策
- [`./identity.md`](./identity.md):底层身份字段集合(userinfo claims 的源数据)
- ADR-0002 PR review 3 条补建议([落档](https://github.com/kevinfitzroy/rushes-lab/issues/17#issuecomment-4460312509))在本契约 §5 / §8 / §10 中落实
- OIDC 1.0 标准:<https://openid.net/specs/openid-connect-core-1_0.html>
- OIDC Discovery 1.0:<https://openid.net/specs/openid-connect-discovery-1_0.html>
- OAuth 2.0 Authorization Framework (RFC 6749):<https://www.rfc-editor.org/rfc/rfc6749>
- OAuth 2.0 PKCE (RFC 7636):<https://www.rfc-editor.org/rfc/rfc7636>

## 版本

- **当前版本:** v1
- **状态:** draft
- **变更日志:**
  - 2026-05-15: initial draft (feishu agent)

## 通用约定

### Issuer URL(`iss`)

bridge 配置项 `OIDC_ISSUER`(env)的值,即 OIDC discovery 文档 `issuer` 字段。**所有签发的 `id_token.iss` 与此严格相等**。

⚠️ **稳定性约束(advisor 提的关键事项):** `iss` 一旦定下**不可轻易变**:
- 已签发的所有 `id_token` 的 `iss` 字段会和 RP 缓存的 discovery `issuer` 不匹配 → 集体失效
- RP 已注册的 OIDC client metadata 包含 `issuer` 引用 → 全部需要重配
- 部署期建议直接用业务域名(`https://id.<company>.com/oidc`)而非测试域 / IP,DNS 切换 IP 不影响 issuer

测试服当前 issuer:`https://rusheslab.taoxiplan.com/oidc`(已在 ADR-0002 §"测试环境运行时配置"记录)。

### Base path

所有端点以 `/oidc` 为前缀(与 [`approval.md`](./approval.md) / [`identity.md`](./identity.md) / [`approval-seafile.md`](./approval-seafile.md) 的 `/v1` 前缀**不同体系**;OIDC 是国际标准协议,不走 bridge 内部 v1 命名空间)。

### Content-Type

- request body(token endpoint):`application/x-www-form-urlencoded`(OAuth 2.0 标准,非 JSON)
- response:`application/json; charset=utf-8`,除 JWKS(`application/json`,无 charset)

### 时间表示

JWT 内时间字段(`iat` / `exp` / `nbf`)按 OIDC 标准用 **Unix epoch 秒(integer)**;与 bridge 其他契约的 ISO 8601 字符串不同 —— 这是 OIDC 标准强制。

### 错误响应通用结构(OAuth 2.0 标准)

```json
{
  "error": "<oauth-error-code>",
  "error_description": "<human-readable>",
  "error_uri": "<optional doc URL>"
}
```

错误码枚举见各端点节;`error` 必为 OAuth 2.0 / OIDC 标准之一,**不**用 bridge 内部 `code` 风格。

## 1. 端点清单

| Endpoint | Method | 用途 | 认证 |
| --- | --- | --- | --- |
| [`/oidc/.well-known/openid-configuration`](#2-get-oidcwell-knownopenid-configuration--discovery) | GET | OIDC discovery metadata | 公开,无认证 |
| [`/oidc/authorize`](#3-get-oidcauthorize--authorization-endpoint) | GET | 启动 authorization code flow | 客户端在 query 标识(`client_id`),用户认证由 bridge → 飞书 OAuth 完成 |
| [`/oidc/token`](#4-post-oidctoken--token-endpoint) | POST | 用 authorization code 或 refresh_token 换 access_token + id_token | client_secret(Basic 或 form 字段)|
| [`/oidc/userinfo`](#5-get-oidcuserinfo--userinfo-endpoint) | GET | 拿用户信息 | Bearer access_token |
| [`/oidc/jwks.json`](#6-get-oidcjwksjson--jwks-endpoint) | GET | 公开签名公钥 | 公开,无认证 |

## 2. GET `/oidc/.well-known/openid-configuration` — Discovery

**用途:** 标准 OIDC discovery,RP 启动时拉取,从中获取所有其他端点 URL + 支持能力。

**Request:** 无参数。

**Response 200:** JSON

| 字段 | 类型 | 值(v1 冻结) | 说明 |
| --- | --- | --- | --- |
| `issuer` | string | `<OIDC_ISSUER>` | 等于 `iss` claim 值 |
| `authorization_endpoint` | string | `<iss>/authorize` | — |
| `token_endpoint` | string | `<iss>/token` | — |
| `userinfo_endpoint` | string | `<iss>/userinfo` | — |
| `jwks_uri` | string | `<iss>/jwks.json` | — |
| `response_types_supported` | array | `["code"]` | v1 仅 authorization code flow |
| `subject_types_supported` | array | `["public"]` | 不实现 pairwise sub |
| `id_token_signing_alg_values_supported` | array | `["RS256"]` | RSA-SHA256(ADR-0002 §1) |
| `scopes_supported` | array | `["openid", "profile", "email", "groups"]` | v1 集合,见 §3 |
| `claims_supported` | array | `["sub", "name", "email", "preferred_username", "groups", "feishu_open_id", "iss", "aud", "iat", "exp", "nbf"]` | 见 §7 |
| `grant_types_supported` | array | `["authorization_code", "refresh_token"]` | v1 仅这两种 |
| `code_challenge_methods_supported` | array | `["S256", "plain"]` | PKCE 支持但不强制(见 §11) |
| `token_endpoint_auth_methods_supported` | array | `["client_secret_basic", "client_secret_post"]` | client_secret 走 Basic header 或 form 字段 |
| `response_modes_supported` | array | `["query"]` | v1 仅 query redirect(不支持 fragment / form_post) |

### 2.1 Discovery 缓存语义(RP 与 bridge 双方约定)

> ⚠️ **OIDC 标准行为 + advisor 提的关键约定:**
>
> - RP 通常**缓存 discovery 文档数小时**(具体由 RP 实现决定;常见值 1-24h)
> - bridge 修改 discovery metadata **不会立即被 RP 看到**;关键字段(`issuer` / `authorization_endpoint` / `token_endpoint` / `userinfo_endpoint` / `jwks_uri`)**严禁热修改**
> - **可热修改**(等 RP 自然过期):`scopes_supported` / `claims_supported` / `code_challenge_methods_supported` 等能力声明
> - 紧急情况下需要全 RP 立即生效的变更,bridge 部署侧负责通知 RP 主动 invalidate cache(运维操作,不属于本契约)

### Errors

| HTTP | 含义 |
| --- | --- |
| 500 | 服务器故障(本应永不发生 —— discovery 是静态 metadata) |

## 3. GET `/oidc/authorize` — Authorization Endpoint

**用途:** 启动 authorization code flow。RP 把用户浏览器重定向到此 endpoint,bridge 内部转飞书 OAuth,最终把 authorization code 通过 redirect 回 RP。

**Query 参数:**

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `response_type` | string | ✓ | 必为 `code`;否则 `unsupported_response_type` |
| `client_id` | string | ✓ | bridge 静态注册的 client ID;不存在则 `unauthorized_client` |
| `redirect_uri` | string (URL) | ✓ | **必须与 client 注册时的 redirect_uri 字面相等**(OIDC 标准:不允许部分匹配 / wildcard);不匹配则 `invalid_request`(且 bridge 不重定向回不在白名单的 URI) |
| `scope` | string | ✓ | 空格分隔 scope 列表,**必须含 `openid`**;其他可选项:`profile`(name / preferred_username)、`email`(email)、`groups`(groups);`feishu_open_id` 始终返(无对应 scope) |
| `state` | string | 推荐 | RP 生成的 CSRF token;bridge 原样回传到 redirect callback。**强烈推荐**,bridge 不强制 |
| `nonce` | string | 推荐 | RP 生成的随机值,bridge 写入 `id_token.nonce` claim 防重放;**推荐**,bridge 不强制 |
| `code_challenge` | string | 条件 | PKCE 标准;若 RP 用 PKCE 则必填 |
| `code_challenge_method` | enum (`S256` / `plain`) | 条件 | 若 `code_challenge` 必填则必填;**推荐 `S256`** |
| `prompt` | enum (`none` / `login` / `consent` / `select_account`) | 否 | v1 **不实现复杂 prompt 行为**;任何值传入都按"正常 flow"处理(不报错,但行为同 omitted)。**RP 若依赖 `prompt=none` 做静默续期,应改用 refresh_token grant** |
| `max_age` | integer | 否 | v1 **忽略**(不实现) |

**成功流程:**

```
1. RP 重定向用户浏览器到 GET /oidc/authorize?... (上述参数)
2. bridge 校验 client_id / redirect_uri / scope / response_type
3. bridge 生成 internal_session_id,持久化 {client_id, redirect_uri, state, nonce, scope,
   code_challenge?, code_challenge_method?},
   重定向用户浏览器到飞书 /authen/v1/index(飞书 OAuth)
4. 用户在飞书完成 OAuth → 飞书重定向回 bridge /login/callback?code=<feishu_code>
5. bridge 用 feishu_code 换 user_access_token → 拉 /authen/v1/user_info → 得到 open_id / union_id
6. bridge 通过 MS-FB-002 内部缓存补充其余字段(name / email / department_chain 等)
7. bridge 生成 authorization_code(自定义 opaque,bridge 内部存 {sub=union_id, claims_snapshot,
   client_id, redirect_uri, scope, nonce, code_challenge*}; TTL 10 min)
8. bridge 重定向用户浏览器到 RP 的 redirect_uri?code=<bridge_code>&state=<原 state>
```

### 3.1 Errors

错误返回**分两种**(OIDC 标准):

#### a. 不可重定向错误(直接显示给用户)

bridge 在 §3 step 2 校验 `client_id` / `redirect_uri` 失败时,**不重定向**到 redirect_uri(可能是恶意域),而是直接展示错误页:

| HTTP | error 文案 | 触发条件 |
| --- | --- | --- |
| 400 | `invalid_request: client_id missing or unknown` | `client_id` 未注册 |
| 400 | `invalid_request: redirect_uri mismatch` | `redirect_uri` 与注册不字面相等 |

#### b. 可重定向错误(通过 redirect_uri 回 RP)

`client_id` / `redirect_uri` 校验通过后的其他错误,**重定向回 redirect_uri**,query 含 `error` + `error_description` + `state`(原值回传):

| `error` 值 | 触发条件 |
| --- | --- |
| `unsupported_response_type` | `response_type != "code"` |
| `invalid_scope` | scope 不含 `openid`,或含未声明的 scope |
| `invalid_request` | `code_challenge_method` 给定但 `code_challenge` 缺 / 反之 / `state` 长度超限(> 1024 字符)等 |
| `server_error` | 飞书 OAuth 5xx / bridge 内部异常 |
| `temporarily_unavailable` | 飞书 OAuth 限频 / 短暂不可用 |
| `access_denied` | 用户在飞书页面拒绝授权 |

## 4. POST `/oidc/token` — Token Endpoint

**用途:** 换 token。支持两种 grant:
1. `authorization_code` —— 用 §3 拿到的 code 换 access_token + id_token + refresh_token
2. `refresh_token` —— 用 refresh_token 续约 access_token(rotation,见 §10)

**Headers:**

- `Content-Type: application/x-www-form-urlencoded`(OAuth 2.0 标准,非 JSON)
- `Authorization: Basic base64(client_id:client_secret)` **或** body 含 `client_id` + `client_secret`(二选一,二者**不能同时**)

### 4.1 `grant_type=authorization_code`

**Body 字段:**

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `grant_type` | ✓ | `authorization_code` |
| `code` | ✓ | §3 step 8 redirect 回 RP 的 code |
| `redirect_uri` | ✓ | 必须等于 authorize 阶段传入的 redirect_uri |
| `code_verifier` | 条件 | 若 authorize 阶段传入 `code_challenge` 则必填(PKCE) |

**Response 200:** JSON

| 字段 | 类型 | 值 |
| --- | --- | --- |
| `access_token` | string | opaque 字符串(non-JWT),用于 userinfo endpoint |
| `token_type` | string | `Bearer`(固定) |
| `expires_in` | integer | access_token TTL(秒);v1 = `3600`(1 小时) |
| `refresh_token` | string | opaque 字符串;v1 TTL = `2592000`(30 天) |
| `id_token` | string | JWT RS256,claims 见 §7 |
| `scope` | string | 实际授予的 scope(可能裁剪掉未授权项) |

**Errors:**

```json
{ "error": "<oauth-error-code>", "error_description": "..." }
```

| HTTP | `error` | 触发 |
| --- | --- | --- |
| 401 | `invalid_client` | client_id / client_secret 不匹配 |
| 400 | `invalid_grant` | code 不存在 / 已用过 / 过期(> 10 min) / 与 client_id 不匹配 / redirect_uri 不一致 / code_verifier 校验失败(PKCE) |
| 400 | `unsupported_grant_type` | `grant_type` 不在 v1 枚举 |
| 400 | `invalid_request` | body 缺字段 |

### 4.2 `grant_type=refresh_token`

**Body 字段:**

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `grant_type` | ✓ | `refresh_token` |
| `refresh_token` | ✓ | §4.1 拿到的 refresh_token |
| `scope` | 否 | 可选裁剪 scope(不可扩);省略则继承原 scope |

**Response 200:** 与 §4.1 同结构。

**Rotation 语义:** bridge **每次 refresh 都返新 refresh_token + 旧 refresh_token 立即失效**(防重放;ADR-0002 §4)。RP 必须**始终用最新 refresh_token**;若使用过期 / 失效的 refresh_token → `invalid_grant`,RP 应让用户重新走 §3 authorize。

**Errors:** 同 §4.1。常见:

| HTTP | `error` | 触发 |
| --- | --- | --- |
| 400 | `invalid_grant` | refresh_token 不存在 / 已过期(> 30 天) / 已被 rotate / 用户已离职(主动失效,见 §10) |

## 5. GET `/oidc/userinfo` — UserInfo Endpoint

**用途:** RP 用 access_token 拉用户 claims。

**Headers:**

- `Authorization: Bearer <access_token>` —— 必填

**Response 200:** JSON,**与 ID Token claims §7 字段集合完全一致**(除标准 JWT 字段 `iss` / `aud` / `iat` / `exp` / `nbf` / `nonce` 不出现在 userinfo)。

**关键字段:**

| Claim | 类型 | scope 要求 | 说明 |
| --- | --- | --- | --- |
| `sub` | string | `openid` | 飞书 `union_id`;**OIDC 主键** |
| `name` | string | `profile` | 飞书 `user.name` |
| `email` | string \| null | `email` | 飞书 `user.email`;**可 null**(见 [`identity.md`](./identity.md) §"字段 null 语义") |
| `preferred_username` | string | `profile` | `email` 非 null 时取 `email`,否则 `name` |
| `groups` | array of string | `groups` | 飞书 `department_chain[].open_department_id` 数组(见 §8) |
| `feishu_open_id` | string | (无 scope,始终返) | 飞书本应用域 `open_id`,自定义 claim |

**Errors:**

| HTTP | `error`(WWW-Authenticate header)| 触发 |
| --- | --- | --- |
| 401 | `invalid_token` | access_token 不存在 / 已过期(> 1 小时)/ 已撤销 |
| 403 | `insufficient_scope` | 当前 access_token 的 scope 不含请求的 claim 所需 scope(v1 不主动检测;RP 自己判断) |

## 6. GET `/oidc/jwks.json` — JWKS Endpoint

**用途:** 暴露 bridge 签 id_token 用的公钥(JWK Set 格式),供 RP 验证 id_token 签名。

**Response 200:** JSON

```json
{
  "keys": [
    {
      "kty": "RSA",
      "use": "sig",
      "kid": "<key-id>",
      "alg": "RS256",
      "n": "<base64url-encoded modulus>",
      "e": "AQAB"
    }
    // ... possibly more keys during rotation window
  ]
}
```

**密钥轮转期(advisor 提的 ADR-0002 §1 关注点):** bridge 暴露 **新 + 旧 2 个 kid**,id_token `header.kid` 字段指向当前签发 key;RP 用 `header.kid` 查 JWKS 找到对应公钥即可。**RP 必须支持多 key**,不依赖 jwks 文档只有 1 个 entry。

**缓存语义:**

- RP 通常缓存 JWKS 数小时
- 新 key 加入后**至少等 RP 缓存周期**(推荐 24h)再用其签 id_token,确保 RP 已拉到新 kid
- 旧 key 失效时,先从 jwks 文档移除,**等所有用旧 key 签的 id_token 自然过期**(1h 后),再物理删除

## 7. ID Token claims

bridge 签发的 id_token 是 **JWT (RS256)**,payload 含以下 claims(具体来源映射见 [ADR-0002 §"JWT claims ↔ 飞书字段映射"](../decisions/0002-bridge-as-oidc-provider.md#2-jwt-claims--飞书字段映射)):

| Claim | 类型 | 必返 | 说明 |
| --- | --- | --- | --- |
| `iss` | string | ✓ | `OIDC_ISSUER`(等于 discovery `issuer`)|
| `sub` | string | ✓ | 飞书 `union_id` |
| `aud` | string \| array | ✓ | RP 的 `client_id` |
| `iat` | integer | ✓ | 签发时刻(Unix epoch 秒)|
| `exp` | integer | ✓ | 过期时刻;v1 = `iat + 3600`(1 小时)|
| `nbf` | integer | 否 | not-before;v1 = `iat`(同 iat,无延迟生效)|
| `nonce` | string | 条件 | RP 在 authorize 阶段传 `nonce` 时必返(原样回传);**RP 必须在收到 id_token 后校验 `nonce`** |
| `name` | string | scope `profile` | — |
| `email` | string \| null | scope `email` | — |
| `preferred_username` | string | scope `profile` | — |
| `groups` | array of string | scope `groups` | 见 §8 |
| `feishu_open_id` | string | ✓(始终返,无 scope 门) | 飞书本应用域 open_id |

**JWT header:**

```json
{ "alg": "RS256", "typ": "JWT", "kid": "<current-signing-key-id>" }
```

## 8. `groups` claim 语义(advisor 补建议落实)

`groups` claim 由 ADR-0002 PR review 补建议 #1 要求显式定义:

| 维度 | 约定 |
| --- | --- |
| **格式** | JSON array of string,每个 string 是飞书 `open_department_id`(形如 `od-xxxxxxxxxxxx`);**opaque 标识**,RP 不可解析其语义 |
| **顺序** | 按飞书返回顺序(主部门优先),数组首项**通常**是主部门;但 v1 **不**保证此顺序稳定 —— RP 不应依赖位置语义 |
| **空数组语义** | 用户**当前**不属于任何部门(可能因 bridge 缓存层 vs 飞书状态差,或刚入职未分配),并不意味着账号无效;status 字段在 [`identity.md`](./identity.md) MS-FB-002 才是权威 |
| **RP 侧 mapping 期望** | **本契约不规定 RP 如何映射 group → role / permission**。两种推荐路径:<br>(a) RP 内置配置:RP 后台配 group→role 规则(如 NC `groups_*` 配置)<br>(b) 上游业务层映射:RP 把 `groups` claim 透传到 material-storage 业务策略层,由后者按"open_department_id → 资源类别"业务规则映射 |
| **变更频率** | 每次 SSO 登录 / refresh 时**重新计算**(读 bridge MS-FB-002 缓存);**离线期间用户被调部门,id_token 内 groups 不更新,直到 access_token 自然过期 + refresh** |
| **不实现** | `roles` claim、`permissions` claim 等 RBAC 类自定义 claim —— v1 仅暴露 `groups`,业务层语义由上游解释 |

## 9. 完整时序图(authorization code flow + refresh)

```
RP                                  Bridge                              飞书
 │ 1. discovery (one-time, cached)   │                                    │
 │──────────────────────────────────▶│                                    │
 │◀──── openid-configuration ────────│                                    │
 │                                                                        │
 │ 2. user clicks "Login with Feishu" → RP redirects browser:             │
 │ GET /oidc/authorize?response_type=code&client_id=...&redirect_uri=...  │
 │   &scope=openid+profile+email+groups&state=...&nonce=...               │
 │──────────────────────────────────▶│                                    │
 │                                   │ 3. validate, store session         │
 │                                   │ → redirect to feishu /authen/v1/   │
 │                                   │   index                            │
 │                                   │───────────────────────────────────▶│
 │                                   │                                    │ user OAuth
 │                                   │◀──── code, state ─────────────────│
 │                                   │                                    │
 │                                   │ 4. exchange code → user_access_tok │
 │                                   │───────────────────────────────────▶│
 │                                   │◀──── tokens, open_id, union_id ───│
 │                                   │ 5. MS-FB-002 缓存补字段             │
 │                                   │ 6. generate bridge_code (TTL 10min)│
 │ 7. redirect to RP redirect_uri?code=<bridge_code>&state=<orig>         │
 │◀──────────────────────────────────│                                    │
 │                                                                        │
 │ 8. POST /oidc/token grant=authorization_code code=<...>                │
 │    Authorization: Basic ...                                            │
 │──────────────────────────────────▶│                                    │
 │                                   │ 9. validate code/PKCE/client       │
 │                                   │ 10. sign id_token (RS256, kid)     │
 │                                   │     + opaque access_token          │
 │                                   │     + opaque refresh_token         │
 │◀── access_token, id_token, refresh_token, expires_in=3600 ─────────────│
 │                                                                        │
 │ 11. verify id_token (sig via jwks.json, iss, aud, exp, nonce)          │
 │                                                                        │
 │ 12. (per-request) GET /oidc/userinfo Authorization: Bearer ...         │
 │──────────────────────────────────▶│                                    │
 │◀── claims JSON ───────────────────│                                    │
 │                                                                        │
 │ ===== 1 hour later, access_token expired =====                         │
 │                                                                        │
 │ 13. POST /oidc/token grant=refresh_token refresh_token=...             │
 │──────────────────────────────────▶│                                    │
 │                                   │ 14. rotate: invalidate old rt,     │
 │                                   │     issue new rt + new access_tok  │
 │◀── new access_token, new refresh_token, new id_token ──────────────────│
```

## 10. Refresh token 行为(ADR-0002 §4 落实)

| 属性 | v1 值 |
| --- | --- |
| 格式 | Opaque 字符串(UUID 或 256-bit 随机);**非 JWT**(RP 不可解析) |
| 存储 | bridge 内部 Redis;key=`refresh:<token>`,value={`sub`, `client_id`, `scope`, `nonce_at_issue`, `created_at`, `expires_at`} |
| TTL | 30 天(2592000 秒) |
| Rotation | **每次成功 refresh,旧 token 立即失效 + 返回新 token**;防重放 |
| 主动撤销触发器 | (a) 用户离职(`contact.user.deleted_v3` 事件 → bridge 主动失效该 `sub` 的所有未过期 refresh_token);(b) RP 调专用 revoke endpoint(v1 **不实现**,见 §13 v1.x 评估) |
| Race condition 容错 | 同一 RP 在网络抖动期可能并发用同一 refresh_token 发起两次 refresh;bridge 行为:**第一个成功 + 旋转;第二个返 `invalid_grant`**。RP 应有重试 + 容忍机制 |

## 11. PKCE(RFC 7636)

**v1 行为:支持 + 推荐 + 不强制。**

- RP 在 authorize 阶段可选传入 `code_challenge` + `code_challenge_method=S256`(推荐)
- 若传入,bridge 在 token endpoint 强制校验 `code_verifier`
- 若未传入,bridge 允许(向 confidential client 兼容)
- **v1.x 评估:对 public client 强制 PKCE**(目前 v1 所有 RP 都是 confidential client + client_secret,PKCE 是额外深度防御)

## 12. 安全约定汇总

| 项 | v1 约定 |
| --- | --- |
| HTTPS | **强制**;bridge 接收的所有 OIDC 请求必须走 HTTPS。Caddy 终结 TLS,uvicorn 内部 HTTP(127.0.0.1)|
| `iss` 稳定性 | **不可热修改**;变更=破坏向后兼容 → 见 §2.1 + 本契约 §14 |
| redirect_uri 严格匹配 | 字面相等,无 wildcard 无后缀匹配 |
| `state` 推荐 | RP 必须生成 + 校验;bridge 不强制,但 RP 不传 = CSRF 风险自负 |
| `nonce` 推荐 | 同上;若传则 bridge 写入 id_token,RP 必须校验 |
| Token storage(RP 侧) | bridge **不规定** RP 如何存 access_token / refresh_token;RP 按自身风控选择(secure cookie / encrypted store / etc.)|
| Token storage(bridge 侧) | refresh_token 在 Redis(必须开 AOF / 持久化);id_token 不存储(签发即丢);access_token 内部映射 Redis,与 refresh 同 |
| 签名密钥 | RS256 / 2048 bit;私钥 0600 root only,见 [ADR-0002 §"id_token 签名密钥管理"](../decisions/0002-bridge-as-oidc-provider.md#1-id_token-签名密钥管理) |
| Logout / token revocation | **v1 不实现**(见 §13);RP 应控制其本地 session,无需调 bridge |

## 13. v1 不实现 / 未决(汇总)

ADR-0002 §"实现范围"已明示 v1 不实现项,这里汇总并扩 v1.x 评估清单:

| 项 | ADR-0002 / 本契约 | 备注 |
| --- | --- | --- |
| Dynamic Client Registration (RFC 7591) | ADR-0002 §3 拒 | client 数量固定,静态注册 + 增加攻击面避免 |
| Client Credentials grant | ADR-0002 拒 | 业务无 service-to-service token 场景 |
| Implicit flow | ADR-0002 拒 | OIDC 已 deprecated;不安全 |
| Device Code flow (RFC 8628) | ADR-0002 拒 | 无 device 场景 |
| Front-channel / back-channel logout | 本契约拒 | RP 自管 local session |
| Token revocation endpoint (RFC 7009) | 本契约 v1 不实现 | v1.x 评估 |
| Token introspection endpoint (RFC 7662) | 本契约 v1 不实现 | userinfo 已可证活 access_token |
| OIDC `prompt=none` / `max_age` | §3 忽略 | 复杂;无需求 |
| `id_token` encryption(JWE) | 不实现 | 签名足够,不加密 |
| Custom claim `roles` / `permissions` | §8 拒 | 业务语义归 RP / 上游 |
| Pairwise sub | §2 拒 | 多 RP 用同一 sub 简化关联 |
| 多 issuer / 多租户 | 不实现 | 我方单租户场景 |

## 14. 向后兼容承诺

| 变更类型 | v1 → v1.x(允许) | v1 → v2(必要) |
| --- | --- | --- |
| 新增 scope(`offline_access` 等) | ✓ | — |
| 新增 claim(可选返,RP 不感知不受影响) | ✓ | — |
| 新增 grant_type(`token_exchange` 等) | ✓ | — |
| **改 `iss`** | ✗ | ✓(变更=所有已签 token + RP cache 全失效,见 §2.1) |
| 改 `sub` 来源(union_id → 其他) | ✗ | ✓(灾难性变更,见 ADR-0002 §2)|
| 改 endpoint path | ✗ | ✓(影响 RP discovery cache) |
| 改 `id_token_signing_alg`(从 RS256 改) | ✗ | ✓ |
| 删 `claims_supported` 中 claim | ✗ | ✓ |
| 缩短 access_token / refresh_token TTL | ✓(RP 应处理任意 TTL) | — |
| 改 PKCE 从可选到强制 | ✓(RP 应已实现 PKCE)| — |

## 15. 与其他契约的关系

| 契约 | 关系 |
|---|---|
| [`../decisions/0002-bridge-as-oidc-provider.md`](../decisions/0002-bridge-as-oidc-provider.md) | **本契约是 ADR-0002 端点 schema 维度的落地**;ADR-0002 描述"做不做 / 怎么做的子决策",本契约描述"接口字段长什么样" |
| [`./identity.md`](./identity.md) (MS-FB-002) | userinfo / id_token claims 的**数据源**是同一份 bridge 内部用户缓存(MS-FB-002 §"缓存语义"),字段语义一致 |
| [`./sso-seafile.md`](./sso-seafile.md) (MS-FB-006) | **Seafile 作为 RP 的具体接入约定**;依赖本契约的 §2-§7 抽象端点 schema,加上 Seafile-specific 边界(virtual_id / SocialAuthUser 表 / 上线预迁移等) |
| [`./approval.md`](./approval.md) (MS-FB-001) | 无直接耦合;SSO 与审批是两套独立面 |
| 未来 RP 接入(oCIS / NC OIDC / etc.) | 本契约**就是**通用面;新 RP 接入只需在 ADR-0002 §3 静态 client 注册表加一项 + 在本契约规定的端点上跑标准 OIDC client |

## 16. PoC 验收清单

1. [ ] `curl https://<iss>/oidc/.well-known/openid-configuration` 200 + 字段集合符合 §2 v1 冻结值
2. [ ] OIDC discovery conformance(用 <https://openid.net/certification/op-tests> 或简化:lib `oidc-provider-tester` / `mod_auth_openidc` test mode 跑一遍)
3. [ ] `curl https://<iss>/oidc/jwks.json` 200 + 至少含 1 个 RSA 2048-bit key
4. [ ] 端到端 with Seafile(待 Seafile Pro 到位 + MS-FB-006 §9 验收清单同步跑):authorize → 飞书 OAuth → bridge callback → bridge redirect → Seafile POST token → Seafile GET userinfo → Seafile session 建立
5. [ ] id_token JWT 解码 + RS256 验签(用 jwks.json 公钥)+ claims 字段集合 = §7
6. [ ] refresh_token rotation:用 rt 换 access_token,再用同一 rt 换第二次 → 第二次 `invalid_grant`(rotation 实测)
7. [ ] 离职闭环:`contact.user.deleted_v3` 事件触发后,该用户所有未过期 refresh_token 失效(SoT §9 实测窗口期内)
8. [ ] 错误路径:`redirect_uri` 不在白名单 → 错误页(不重定向);`client_id` 不存在 → 错误页;scope 不含 `openid` → redirect 回 RP + `error=invalid_scope`
