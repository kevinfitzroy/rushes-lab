"""通用 OIDC RP + JWT session service(#154:飞书 OIDC 抽象为 provider 配置留口)。

流程(标准 authorization_code + userinfo):
  1. /api/v1/auth/login → build_authorize_url → 重定向 IdP
  2. 用户在 IdP 同意 → 回调 /api/v1/auth/callback?code=...&state=...
  3. exchange_code_for_token → 拿 access_token
  4. fetch_userinfo → 拿 sub / name / email(claim 名可配置映射)
  5. upsert_user → 按 users.oidc_sub 找/建 users 行,返 internal user_id
  6. encode_session → 签 JWT
  7. set cookie ms_session + 302 redirect 到 state.next

provider 配置:settings.oidc_provider(dict,默认空 = 纯本地登录,本服务 enabled=False):
  {
    "authorize_endpoint": "...",   # IdP authorize URL
    "token_endpoint": "...",       # IdP token URL
    "userinfo_endpoint": "...",    # IdP userinfo URL
    "client_id": "...",
    "client_secret": "...",
    "redirect_uri": "...",         # 绝对 URL,需在 IdP 后台注册
    "scope": "...",                # 可选,默认 openid profile email
    "claims": {"sub": "sub", "name": "name", "email": "email"}  # 可选 claim 映射
  }
env 注入:OIDC_PROVIDER='{...json...}'(pydantic-settings 自动 JSON 解析)。

⚠️ 留口边界(接真实 IdP 前必须补齐,勿当已就绪):
  - id_token 不校验:只信任 userinfo 的 HTTP 响应(手写 RP,无 authlib)
  - 无 PKCE(code_challenge / code_verifier)
  - state 仅防 CSRF 简化实现(state=nonce),无 id_token_hint / nonce claim 校验
  - 单测覆盖 upsert 的 email 兜底关联分支;网络流(token/userinfo)需在
    容器集成测试里对 mock IdP 验证
"""
from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx
from jose import JWTError, jwt
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.tables import User
from app.settings import Settings

log = logging.getLogger(__name__)

# 从 userinfo 里取值时的默认 claim 名(可被 provider.claims 覆盖)
_DEFAULT_CLAIMS = {"sub": "sub", "name": "name", "email": "email"}
_DEFAULT_SCOPE = "openid profile email"


class OIDCService:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._http = httpx.AsyncClient(timeout=10.0)
        self._cfg: dict[str, Any] = dict(settings.oidc_provider or {})
        self._claims: dict[str, str] = dict(_DEFAULT_CLAIMS)
        self._claims.update(self._cfg.get("claims") or {})

    async def close(self) -> None:
        await self._http.aclose()

    # ─── provider 配置(留口;未配置 = 纯本地登录)─────────────────────────
    @property
    def enabled(self) -> bool:
        """是否配置了可用 provider(纯本地登录时 False)。"""
        return bool(self._cfg.get("authorize_endpoint") and self._cfg.get("token_endpoint")
                    and self._cfg.get("client_id") and self._cfg.get("client_secret"))

    def _claim(self, key: str) -> str:
        return self._claims.get(key, _DEFAULT_CLAIMS[key])

    # ─── OIDC flow ─────────────────────────────────────────────────────────
    def build_authorize_url(self, state: str) -> str:
        """生成 IdP authorize URL(state 是 callback 校验用的随机 nonce)。"""
        params = {
            "client_id": self._cfg["client_id"],
            "response_type": "code",
            "redirect_uri": self._cfg["redirect_uri"],
            "scope": self._cfg.get("scope") or _DEFAULT_SCOPE,
            "state": state,
        }
        return f"{self._cfg['authorize_endpoint']}?{urlencode(params)}"

    @staticmethod
    def generate_state() -> tuple[str, str]:
        """生成 state token(nonce)+ 内部 payload(供 callback 校验)。

        实现:state = random nonce;cookie 'ms_oidc_state' 存 nonce,
        callback 比对 state == nonce。next 走单独 cookie 'ms_oidc_next'。
        """
        nonce = secrets.token_urlsafe(24)
        return nonce, nonce  # 简化:state 即 nonce

    async def exchange_code_for_token(self, code: str) -> dict[str, Any]:
        """code → access_token(标准 OAuth2 authorization_code,凭据 in body)。"""
        resp = await self._http.post(
            self._cfg["token_endpoint"],
            data={
                "grant_type": "authorization_code",
                "client_id": self._cfg["client_id"],
                "client_secret": self._cfg["client_secret"],
                "code": code,
                "redirect_uri": self._cfg["redirect_uri"],
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        if "access_token" not in data:
            raise RuntimeError(f"OIDC token exchange failed: {data}")
        return data

    async def fetch_userinfo(self, access_token: str) -> dict[str, Any]:
        """access_token → user info(sub / name / email / picture)。"""
        resp = await self._http.get(
            self._cfg["userinfo_endpoint"],
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        return resp.json()

    async def _find_by_sub(self, db: AsyncSession, sub: str) -> User | None:
        res = await db.execute(select(User).where(User.oidc_sub == sub))
        return res.scalar_one_or_none()

    async def _find_by_email(self, db: AsyncSession, email: str) -> User | None:
        """按 email 找已有本地账号(email 列无唯一约束,理论上可能多命中)。

        多命中时取 created_at 最早的一个(确定性),并告警供排查。
        """
        res = await db.execute(select(User).where(func.lower(User.email) == email))
        matches = list(res.scalars().all())
        if len(matches) > 1:
            log.warning("OIDC email %s 命中 %d 个本地账号,取最早创建的一个", email, len(matches))
            return min(matches, key=lambda u: u.created_at)
        return matches[0] if matches else None

    async def upsert_user_from_userinfo(
        self, db: AsyncSession, userinfo: dict[str, Any]
    ) -> User:
        """IdP userinfo → upsert users 表,返 ORM User 对象。

        匹配顺序(F16:防 IdP 首登时已有本地账号被重复建号):
          1. oidc_sub(provider 的 sub claim;ADR-0007 起 OIDC 用户的身份匹配键)
          2. email 兜底关联 — sub miss 时,若 userinfo 带 email,先按 email
             找已有本地账号并绑定 oidc_sub;仅当该账号尚未绑定其它 oidc_sub
             才关联(避免把已属于别的 IdP 身份的账号抢过来)。
          两路都 miss → 新建 User。
        """
        sub = userinfo.get(self._claim("sub")) or userinfo.get("sub")
        if not sub:
            raise RuntimeError(f"OIDC userinfo missing sub: {userinfo}")
        email = (userinfo.get(self._claim("email")) or userinfo.get("email") or "").strip().lower()

        user = await self._find_by_sub(db, sub)
        if user is None and email:
            user = await self._find_by_email(db, email)
            if user is not None and user.oidc_sub not in (None, sub):
                log.warning(
                    "OIDC email %s 已被 oidc_sub=%s 占用,不抢占,按新用户建号",
                    email, user.oidc_sub,
                )
                user = None

        if user is None:
            default_org = self._settings.default_organization_id
            org_uuid = uuid.UUID(default_org) if default_org else None
            user = User(
                oidc_sub=sub,
                name=userinfo.get(self._claim("name")) or userinfo.get("name") or "unknown",
                email=userinfo.get(self._claim("email")) or userinfo.get("email"),
                is_active=True,
                organization_id=org_uuid,
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
            log.info("created user from OIDC sub=%s name=%s org=%s",
                     sub, user.name, org_uuid)
            return user

        # 命中已有用户:email 兜底关联时补绑 sub;同步可能变化的字段
        changed = False
        if user.oidc_sub != sub:
            user.oidc_sub = sub
            changed = True
        new_name = userinfo.get(self._claim("name")) or userinfo.get("name")
        if new_name and user.name != new_name:
            user.name = new_name
            changed = True
        new_email = userinfo.get(self._claim("email")) or userinfo.get("email")
        if new_email and user.email != new_email:
            user.email = new_email
            changed = True
        # backfill organization_id(老 user 没绑 org)
        if user.organization_id is None and self._settings.default_organization_id:
            user.organization_id = uuid.UUID(self._settings.default_organization_id)
            changed = True
        if changed:
            await db.commit()
            await db.refresh(user)

        return user

    # ─── session JWT ───────────────────────────────────────────────────────
    def encode_session(self, user: User) -> str:
        now = datetime.now(timezone.utc)
        payload = {
            "sub": str(user.id),
            "name": user.name,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=self._settings.session_jwt_ttl_seconds)).timestamp()),
        }
        return jwt.encode(
            payload,
            self._settings.session_jwt_secret,
            algorithm=self._settings.session_jwt_alg,
        )

    def decode_session(self, token: str) -> dict[str, Any]:
        try:
            return jwt.decode(
                token,
                self._settings.session_jwt_secret,
                algorithms=[self._settings.session_jwt_alg],
            )
        except JWTError as e:
            raise ValueError(f"invalid session token: {e}") from e


async def create_auth_service(settings: Settings) -> OIDCService:
    return OIDCService(settings)
