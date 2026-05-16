"""auth router — 飞书 OIDC RP(Phase B-2 iter5)。

endpoints:
  GET  /api/v1/auth/login           → 302 → 飞书 authorize
  GET  /api/v1/auth/callback        → exchange code + set session cookie + redirect next
  GET  /api/v1/auth/me              → 返当前 session user(JSON)
  POST /api/v1/auth/logout          → 清 session cookie
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.tables import User
from app.deps import CurrentUser, get_current_user
from app.services.auth import FeishuOIDCService
from app.settings import get_settings

log = logging.getLogger(__name__)
router = APIRouter()


# 复用 lifespan-wired single service instance
def get_auth_service(request: Request) -> FeishuOIDCService:
    return request.app.state.auth


_OIDC_STATE_COOKIE = "ms_oidc_state"
_OIDC_NEXT_COOKIE = "ms_oidc_next"
_DEFAULT_AFTER_LOGIN = "/"


@router.get("/login")
async def login(
    next: str = Query(default=_DEFAULT_AFTER_LOGIN, description="登录后回跳地址(相对路径)"),
    auth: FeishuOIDCService = Depends(get_auth_service),
) -> RedirectResponse:
    nonce, _ = FeishuOIDCService.generate_state()
    url = auth.build_authorize_url(state=nonce)

    resp = RedirectResponse(url=url, status_code=302)
    settings = get_settings()
    # state cookie(防 CSRF)+ next cookie(透传 redirect 目标)
    common = {
        "httponly": True,
        "secure": settings.session_cookie_secure,
        "samesite": settings.session_cookie_samesite,
        "max_age": 600,   # 10 min,callback 必须在此期内完成
        "path": "/api/v1/auth",
    }
    resp.set_cookie(_OIDC_STATE_COOKIE, nonce, **common)
    resp.set_cookie(_OIDC_NEXT_COOKIE, next, **common)
    return resp


@router.get("/callback")
async def callback(
    code: str = Query(...),
    state: str = Query(...),
    expected_state: str | None = Cookie(default=None, alias=_OIDC_STATE_COOKIE),
    next_url: str = Cookie(default=_DEFAULT_AFTER_LOGIN, alias=_OIDC_NEXT_COOKIE),
    db: AsyncSession = Depends(get_db),
    auth: FeishuOIDCService = Depends(get_auth_service),
) -> RedirectResponse:
    if expected_state is None or state != expected_state:
        raise HTTPException(400, "state mismatch(可能 CSRF 或 cookie 过期,请重新 /login)")

    # 1) code → access_token
    token = await auth.exchange_code_for_token(code)
    # 2) access_token → userinfo
    userinfo = await auth.fetch_userinfo(token["access_token"])
    # 3) upsert
    user = await auth.upsert_user_from_userinfo(db, userinfo)
    if not user.is_active:
        raise HTTPException(403, "用户已离职 / 被禁用,请联系管理员")

    # 4) 签 session JWT + set cookie
    session_token = auth.encode_session(user)
    settings = get_settings()
    resp = RedirectResponse(url=next_url, status_code=302)
    resp.set_cookie(
        settings.session_cookie_name,
        session_token,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite=settings.session_cookie_samesite,
        max_age=settings.session_jwt_ttl_seconds,
        path="/",
    )
    # 清 OIDC 中间 cookie
    resp.delete_cookie(_OIDC_STATE_COOKIE, path="/api/v1/auth")
    resp.delete_cookie(_OIDC_NEXT_COOKIE, path="/api/v1/auth")
    log.info("login success user_id=%s open_id=%s", user.id, user.feishu_open_id)
    return resp


@router.get("/me")
async def me(
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    user = await db.get(User, cur.id)
    if not user:
        raise HTTPException(401, "session user not found")
    return {
        "id": str(user.id),
        "open_id": user.feishu_open_id,
        "union_id": user.feishu_union_id,
        "name": user.name,
        "email": user.email,
        "organization_id": str(user.organization_id) if user.organization_id else None,
        "is_active": user.is_active,
    }


@router.post("/logout")
async def logout() -> JSONResponse:
    settings = get_settings()
    resp = JSONResponse({"status": "ok"})
    resp.delete_cookie(settings.session_cookie_name, path="/")
    return resp
