"""FastAPI Dependency Injection — Phase B-2 iter4 + iter5。"""
from __future__ import annotations

import uuid

from fastapi import Header, HTTPException, Request

from app.services.audit import AuditService
from app.services.auth import FeishuOIDCService
from app.services.permissions import PermissionsService
from app.services.presign import PresignService
from app.settings import Settings, get_settings


def settings_dep() -> Settings:
    return get_settings()


def get_permissions(request: Request) -> PermissionsService:
    return request.app.state.permissions


def get_presign(request: Request) -> PresignService:
    return request.app.state.presign


def get_auth(request: Request) -> FeishuOIDCService:
    return request.app.state.auth


async def get_audit(request: Request):
    """每请求新建 AuditService,绑当前 db session。"""
    from app.db.session import get_sessionmaker
    async with get_sessionmaker()() as session:
        yield AuditService(session)


# ─── current user(Phase B-2 iter5:cookie session 优先 + dev header fallback)─
async def get_current_user_id(
    request: Request,
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
) -> uuid.UUID:
    """认证优先级:
      1. cookie 'ms_session'(JWT)— 生产路径,飞书 OIDC 登录获得
      2. X-User-Id header — dev / smoke 测试 fallback;生产环境 settings.env != 'dev' 时拒绝
    """
    settings = get_settings()
    auth: FeishuOIDCService = request.app.state.auth

    token = request.cookies.get(settings.session_cookie_name)
    if token:
        try:
            payload = auth.decode_session(token)
            return uuid.UUID(payload["sub"])
        except (ValueError, KeyError) as e:
            raise HTTPException(401, f"invalid session: {e}") from e

    # dev fallback
    if settings.env == "dev" and x_user_id:
        try:
            return uuid.UUID(x_user_id)
        except ValueError as e:
            raise HTTPException(400, f"X-User-Id must be valid UUID: {e}") from e

    raise HTTPException(401, "not authenticated — call /api/v1/auth/login")


async def get_request_context(request: Request) -> dict[str, str | None]:
    """请求级 context:IP / User-Agent;给 audit 用。"""
    return {
        "request_ip": request.client.host if request.client else None,
        "user_agent": request.headers.get("user-agent"),
    }
