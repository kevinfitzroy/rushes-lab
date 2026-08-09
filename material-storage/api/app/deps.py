"""FastAPI Dependency Injection — CurrentUser(SQL UUID 作 FK + OpenFGA subject)。"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from fastapi import Header, HTTPException, Request
from sqlalchemy import select

from app.db.session import get_sessionmaker
from app.db.tables import User
from app.services.audit import AuditService
from app.services.auth import OIDCService
from app.services.local_auth import LocalAuthService
from app.services.permissions import PermissionsService
from app.services.presign import PresignService
from app.settings import Settings, get_settings

log = logging.getLogger(__name__)


@dataclass
class CurrentUser:
    """authn 结果 — id 是 SQL UUID,同时做 FK 和 OpenFGA subject(#148 起)。

    #154:飞书 open_id 不再进 session / CurrentUser(登录与权限都不再使用;
    users.feishu_open_id 列保留只读作历史对照)。
    """
    id: uuid.UUID
    name: str

    @property
    def subject(self) -> str:
        """OpenFGA user subject:#148 起一律 user:<users.id UUID>。"""
        return f"user:{self.id}"


def settings_dep() -> Settings:
    return get_settings()


def get_permissions(request: Request) -> PermissionsService:
    return request.app.state.permissions


def get_presign(request: Request) -> PresignService:
    return request.app.state.presign


def get_auth(request: Request) -> OIDCService:
    return request.app.state.auth


def get_local_auth(request: Request) -> LocalAuthService:
    return request.app.state.local_auth  # type: ignore[no-any-return]  # app.state 是 Any


async def get_audit(request: Request):
    """每请求新建 AuditService,绑当前 db session。"""
    from app.db.session import get_sessionmaker
    async with get_sessionmaker()() as session:
        yield AuditService(session)


# #149 review F15:must_change_password=true 的会话,后端只放行以下端点
# (改密页依赖 /me 报告状态、改密端点自身要能过守卫、logout 无鉴权但一并列出);
# 其余端点一律 403,防止拿临时密码的人绕过前端路由守卫直接调 API。
# 口径与 /me 一致:必须已设本地密码才算强制改密(存量飞书用户不误伤)。
_FORCED_CHANGE_OK_ROUTES = frozenset({"me", "change_password", "logout"})


# ─── current user(cookie session 优先 + dev header fallback)─────────────────
async def _load_active_user(uid: uuid.UUID) -> tuple[CurrentUser, bool]:
    """按 users.id 查库,一次拿齐 F5(is_active)+ F15(强制改密)判定所需的列。

    F5:禁用必须立即下线,不能等 JWT 7 天过期 —— 被禁用的用户在所有需要登录的
    端点(含缩略图 URL / 改密 / 通知)一律 401。
    返回 `(CurrentUser, forced_change)`;forced_change 口径与 /me 一致:
    必须已设本地密码才算强制改密(存量飞书用户不误伤)。

    每次认证**一次** PK 查询(users 百人级,可忽略)。注意别拆成两次开 session ——
    缩略图这类高频端点会被每请求两次 round-trip 放大。dev 通道与 JWT 路径共用同一
    实现,保证两边语义一致。
    """
    async with get_sessionmaker()() as db:
        stmt = select(
            User.id, User.name, User.is_active,
            User.must_change_password, User.password_hash,
        ).where(User.id == uid)
        row = (await db.execute(stmt)).first()
        if row is None:
            raise HTTPException(401, "用户不存在或已删除")
        if not row.is_active:
            raise HTTPException(401, "账号已停用,请联系管理员")
        forced_change = bool(row.must_change_password and row.password_hash is not None)
        return CurrentUser(id=row.id, name=row.name), forced_change


async def get_current_user(
    request: Request,
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
) -> CurrentUser:
    """认证优先级:
      1. cookie 'ms_session'(JWT)— 生产路径,本地账号密码登录(#149)或 OIDC 获得;
         F5:解出 sub 后查库校验 is_active(见 _load_active_user),禁用立即 401,名称以库内为准;
         F15:must_change_password=true 时非改密/me/logout 端点拦截(403)
      2. X-User-Id header(dev fallback)— 反查 db;生产 env != 'dev' 拒绝;
         dev 通道不做强制改密拦截(本地开发无密码流程)
    """
    settings = get_settings()
    auth: OIDCService = request.app.state.auth

    token = request.cookies.get(settings.session_cookie_name)
    if token:
        try:
            payload = auth.decode_session(token)
            uid = uuid.UUID(payload["sub"])
        except (ValueError, KeyError) as e:
            log.info("session decode failed: %s", e)
            raise HTTPException(401, "会话已过期或无效,请重新登录") from e
        # F5:is_active 校验放最前 —— 禁用账号任何端点一律 401(含改密/me),
        # 优先于 F15 的 403(禁用状态下的改密诉求无意义)
        user, forced_change = await _load_active_user(uid)
        # F15:强制改密拦截(must_change_password=true 只放行改密/me/logout)
        route_name = getattr(request.scope.get("route"), "name", "")
        if forced_change and route_name not in _FORCED_CHANGE_OK_ROUTES:
            raise HTTPException(
                403, "首次登录请先设置新密码:请先完成修改密码再继续操作"
            )
        return user

    if settings.env == "dev" and x_user_id:
        try:
            uid = uuid.UUID(x_user_id)
        except ValueError as e:
            raise HTTPException(400, "X-User-Id 必须是 UUID 格式") from e
        # dev fallback 反查 db(与 JWT 路径同一校验;dev 不做强制改密拦截)
        user, _ = await _load_active_user(uid)
        return user

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
    from app.services.org import get_default_organization
    async with get_sessionmaker()() as db:
        org = await get_default_organization(db)
    if org:
        _, tenant_key = org
        if await perms.is_org_admin(
            user_id=str(user.id), organization_tenant_key=tenant_key,
        ):
            return user
    if await perms.has_any_project_admin(user_id=str(user.id)):
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
    from app.services.org import get_default_organization
    async with get_sessionmaker()() as db:
        org = await get_default_organization(db)
    if not org:
        raise HTTPException(500, "no default organization configured")
    _, tenant_key = org
    if not await perms.is_org_admin(
        user_id=str(user.id), organization_tenant_key=tenant_key,
    ):
        raise HTTPException(403, "system admin permission required(只有系统管理员可执行此操作)")
    return user


async def get_is_system_admin(
    request: Request,
    user: CurrentUser = _Depends(get_current_user),
) -> bool:
    """返当前 user 是否系统 admin(不抛 403,bool)。

    给业务 endpoint 用作 *直通* 判定:`if is_system_admin or await perms.check(...)`。
    系统 admin 在 *所有* project / folder / asset 上都视为有 admin/upload/download/view 权限,
    避免在每个 router 里复制一份 default-org → is_org_admin → try/except 逻辑。
    """
    perms: PermissionsService = request.app.state.permissions
    from app.services.org import get_default_organization
    async with get_sessionmaker()() as db:
        org = await get_default_organization(db)
    if not org:
        return False
    _, tenant_key = org
    try:
        return await perms.is_org_admin(
            user_id=str(user.id), organization_tenant_key=tenant_key,
        )
    except Exception:  # noqa: BLE001
        return False
