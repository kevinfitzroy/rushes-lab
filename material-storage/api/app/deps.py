"""FastAPI Dependency Injection — iter a1 加 CurrentUser(同时给 SQL UUID 和飞书 open_id)。"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Header, HTTPException, Request
from sqlalchemy import select

from app.db.session import get_sessionmaker
from app.db.tables import User
from app.services.audit import AuditService
from app.services.auth import FeishuOIDCService
from app.services.feishu_client import FeishuClient
from app.services.permissions import PermissionsService
from app.services.presign import PresignService
from app.settings import Settings, get_settings


@dataclass
class CurrentUser:
    """authn 结果 — 同时拿 SQL UUID(FK 用)和飞书 open_id(OpenFGA subject 用)。"""
    id: uuid.UUID
    open_id: str
    name: str


def settings_dep() -> Settings:
    return get_settings()


def get_permissions(request: Request) -> PermissionsService:
    return request.app.state.permissions


def get_presign(request: Request) -> PresignService:
    return request.app.state.presign


def get_auth(request: Request) -> FeishuOIDCService:
    return request.app.state.auth


def get_feishu_client(request: Request) -> FeishuClient:
    return request.app.state.feishu_client


async def get_audit(request: Request):
    """每请求新建 AuditService,绑当前 db session。"""
    from app.db.session import get_sessionmaker
    async with get_sessionmaker()() as session:
        yield AuditService(session)


# ─── current user(cookie session 优先 + dev header fallback)─────────────────
async def get_current_user(
    request: Request,
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
) -> CurrentUser:
    """认证优先级:
      1. cookie 'ms_session'(JWT)— 生产路径,飞书 OIDC 登录获得
         JWT payload 已包 sub(UUID)+ open_id + name → 直接构 CurrentUser,不查 db
      2. X-User-Id header(dev fallback)— 反查 db 拿 open_id;生产 env != 'dev' 拒绝
    """
    settings = get_settings()
    auth: FeishuOIDCService = request.app.state.auth

    token = request.cookies.get(settings.session_cookie_name)
    if token:
        try:
            payload = auth.decode_session(token)
            return CurrentUser(
                id=uuid.UUID(payload["sub"]),
                open_id=payload["open_id"],
                name=payload.get("name", ""),
            )
        except (ValueError, KeyError) as e:
            raise HTTPException(401, f"invalid session: {e}") from e

    if settings.env == "dev" and x_user_id:
        try:
            uid = uuid.UUID(x_user_id)
        except ValueError as e:
            raise HTTPException(400, f"X-User-Id must be valid UUID: {e}") from e
        # dev fallback 反查 db
        async with get_sessionmaker()() as db:
            stmt = select(User).where(User.id == uid)
            res = await db.execute(stmt)
            user = res.scalar_one_or_none()
            if user is None:
                raise HTTPException(401, f"X-User-Id user {uid} not found")
            return CurrentUser(id=user.id, open_id=user.feishu_open_id, name=user.name)

    raise HTTPException(401, "not authenticated — call /api/v1/auth/login")




async def get_request_context(request: Request) -> dict[str, str | None]:
    """请求级 context:IP / User-Agent;给 audit 用。"""
    return {
        "request_ip": request.client.host if request.client else None,
        "user_agent": request.headers.get("user-agent"),
    }


# ─── admin enforce(polish — org admin OR 任意 project admin)─────────────────
from fastapi import Depends as _Depends  # noqa: E402

async def require_admin(
    request: Request,
    user: CurrentUser = _Depends(get_current_user),
) -> CurrentUser:
    """admin 守门 — 给 /admin/* / GET /users 用。

    判定:org admin(organization#admin)或任意 project can_admin。
    """
    perms: PermissionsService = request.app.state.permissions
    from app.services.contact_sync import get_default_organization
    async with get_sessionmaker()() as db:
        org = await get_default_organization(db)
    if org:
        _, tenant_key = org
        if await perms.is_org_admin(
            user_open_id=user.open_id, organization_tenant_key=tenant_key,
        ):
            return user
    if await perms.has_any_project_admin(user_open_id=user.open_id):
        return user
    raise HTTPException(403, "admin permission required")


async def require_system_admin(
    request: Request,
    user: CurrentUser = _Depends(get_current_user),
) -> CurrentUser:
    """系统 admin 守门 — 仅 organization#admin(后台指定,不可 UI promote)。

    用于:POST /projects(只有系统 admin 能建项目)。
    """
    perms: PermissionsService = request.app.state.permissions
    from app.services.contact_sync import get_default_organization
    async with get_sessionmaker()() as db:
        org = await get_default_organization(db)
    if not org:
        raise HTTPException(500, "no default organization configured")
    _, tenant_key = org
    if not await perms.is_org_admin(
        user_open_id=user.open_id, organization_tenant_key=tenant_key,
    ):
        raise HTTPException(403, "system admin permission required(只有系统管理员可执行此操作)")
    return user
