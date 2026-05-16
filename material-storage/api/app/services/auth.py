"""飞书 OIDC RP + JWT session service(Phase B-2 iter5)。

直接接飞书 passport.feishu.cn 标准 OAuth2 / OIDC,不再依赖 feishu-bridge
(iter6 把 webhook handler 也内化到 ms-api,完全去 bridge 化)。

流程:
  1. /api/v1/auth/login → build_authorize_url → 重定向飞书
  2. 用户在飞书同意 → 回调 /api/v1/auth/callback?code=...&state=...
  3. exchange_code_for_token → 拿 access_token
  4. fetch_userinfo → 拿 open_id / union_id / name / email
  5. upsert_user → 找/建 users 行,返 internal user_id
  6. encode_session → 签 JWT
  7. set cookie ms_session + 302 redirect 到 state.next
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.tables import User
from app.settings import Settings

log = logging.getLogger(__name__)


class FeishuOIDCService:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._http = httpx.AsyncClient(timeout=10.0)

    async def close(self) -> None:
        await self._http.aclose()

    # ─── OIDC flow ─────────────────────────────────────────────────────────
    def build_authorize_url(self, state: str, next_url: str | None = None) -> str:
        """生成飞书 OAuth2 authorize URL;next_url 通过 state 透传(callback 解出)。"""
        params = {
            "client_id": self._settings.feishu_app_id,
            "response_type": "code",
            "redirect_uri": self._settings.feishu_redirect_uri,
            "scope": self._settings.feishu_oidc_scope,
            "state": state,
        }
        return f"{self._settings.feishu_authorize_endpoint}?{urlencode(params)}"

    @staticmethod
    def generate_state(next_url: str | None = None) -> tuple[str, str]:
        """生成 state token + 内部 payload(供 callback 校验 + 取回 next_url)。

        实现:state = random nonce;payload = JWT(包 nonce + next_url),
        cookie 'oidc_state' 存 payload,callback 比对 state == payload.nonce。
        """
        nonce = secrets.token_urlsafe(24)
        return nonce, nonce  # 简化:state 即 nonce;next 走单独 cookie 'oidc_next'

    async def exchange_code_for_token(self, code: str) -> dict[str, Any]:
        """code → access_token(标准 OAuth2 client_credentials in body)。"""
        resp = await self._http.post(
            self._settings.feishu_token_endpoint,
            data={
                "grant_type": "authorization_code",
                "client_id": self._settings.feishu_app_id,
                "client_secret": self._settings.feishu_app_secret,
                "code": code,
                "redirect_uri": self._settings.feishu_redirect_uri,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        if "access_token" not in data:
            raise RuntimeError(f"feishu token exchange failed: {data}")
        return data

    async def fetch_userinfo(self, access_token: str) -> dict[str, Any]:
        """access_token → user info(open_id / union_id / name / email / picture)。"""
        resp = await self._http.get(
            self._settings.feishu_userinfo_endpoint,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        return resp.json()

    async def upsert_user_from_userinfo(
        self, db: AsyncSession, userinfo: dict[str, Any]
    ) -> User:
        """飞书 userinfo → upsert users 表,返 ORM User 对象。

        匹配键:open_id(飞书 app 内稳定);union_id 也存(跨 app 关联)。
        """
        open_id = userinfo.get("open_id") or userinfo.get("sub")
        if not open_id:
            raise RuntimeError(f"feishu userinfo missing open_id: {userinfo}")

        stmt = select(User).where(User.feishu_open_id == open_id)
        res = await db.execute(stmt)
        user = res.scalar_one_or_none()

        if user is None:
            import uuid as _uuid
            default_org = self._settings.default_organization_id
            org_uuid = _uuid.UUID(default_org) if default_org else None
            user = User(
                feishu_open_id=open_id,
                feishu_union_id=userinfo.get("union_id"),
                name=userinfo.get("name") or userinfo.get("en_name") or "unknown",
                email=userinfo.get("email") or userinfo.get("enterprise_email"),
                is_active=True,
                organization_id=org_uuid,
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
            log.info("created user from feishu open_id=%s name=%s org=%s",
                     open_id, user.name, org_uuid)
        else:
            # 同步可能变化的字段
            changed = False
            new_name = userinfo.get("name") or userinfo.get("en_name")
            if new_name and user.name != new_name:
                user.name = new_name
                changed = True
            new_email = userinfo.get("email") or userinfo.get("enterprise_email")
            if new_email and user.email != new_email:
                user.email = new_email
                changed = True
            if not user.feishu_union_id and userinfo.get("union_id"):
                user.feishu_union_id = userinfo["union_id"]
                changed = True
            # backfill organization_id(老 user 没绑 org)
            if user.organization_id is None and self._settings.default_organization_id:
                import uuid as _uuid
                user.organization_id = _uuid.UUID(self._settings.default_organization_id)
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
            "open_id": user.feishu_open_id,
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


async def create_auth_service(settings: Settings) -> FeishuOIDCService:
    return FeishuOIDCService(settings)
