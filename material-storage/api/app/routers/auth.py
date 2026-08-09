"""auth router — 飞书 OIDC RP(Phase B-2 iter5)+ 本地账号密码登录(#149)。

endpoints:
  GET  /api/v1/auth/login           → 302 → 飞书 authorize(飞书 OIDC,P4 才下线)
  GET  /api/v1/auth/callback        → exchange code + set session cookie + redirect next
  GET  /api/v1/auth/me              → 返当前 session user(JSON)
  POST /api/v1/auth/logout          → 清 session cookie
  POST /api/v1/auth/local/login     → 账号密码登录(限流 + audit;session JWT 复用 #149)
  POST /api/v1/auth/change-password → 修改密码(首登 must_change_password 强制流程 #149)

#149 约定:本文件只加不删(飞书 OIDC 下线归 #154)。
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.tables import User
from app.deps import (
    CurrentUser,
    get_audit,
    get_current_user,
    get_local_auth,
    get_request_context,
)
from app.models import ChangePasswordIn, LocalLoginIn
from app.services.audit import AuditService
from app.services.auth import FeishuOIDCService
from app.services.local_auth import LocalAuthService
from app.settings import get_settings

log = logging.getLogger(__name__)
router = APIRouter()


# 复用 lifespan-wired single service instance
def get_auth_service(request: Request) -> FeishuOIDCService:
    return request.app.state.auth


_OIDC_STATE_COOKIE = "ms_oidc_state"
_OIDC_NEXT_COOKIE = "ms_oidc_next"
# 默认回 SPA 入口;nginx `/` 路由到 MinIO Console,不能用 "/"
_DEFAULT_AFTER_LOGIN = "/ms-static/web/"


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
    request: Request,
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    user = await db.get(User, cur.id)
    if not user:
        raise HTTPException(401, "session user not found")

    # 查 is_system_admin(organization#admin)给前端判 NewProjectModal 是否可用
    is_system_admin = False
    from app.services.contact_sync import get_default_organization
    org = await get_default_organization(db)
    if org:
        _, tenant_key = org
        perms = request.app.state.permissions
        try:
            is_system_admin = await perms.is_org_admin(
                user_id=str(user.id), organization_tenant_key=tenant_key,
            )
        except Exception:  # noqa: BLE001
            pass

    return {
        "id": str(user.id),
        "open_id": user.feishu_open_id,
        "union_id": user.feishu_union_id,
        "name": user.name,
        "email": user.email,
        "organization_id": str(user.organization_id) if user.organization_id else None,
        "is_active": user.is_active,
        "is_system_admin": is_system_admin,
        # #149:本地认证字段(加在 /me 供前端路由守卫用)。
        # password_set = 是否已设本地密码;must_change_password 仅在已设密码时生效
        # (存量飞书用户无本地密码,must_change_password 对他们是假值,不会误跳改密页)
        "password_set": user.password_hash is not None,
        "must_change_password": bool(user.must_change_password and user.password_hash is not None),
    }


@router.post("/logout")
async def logout() -> JSONResponse:
    settings = get_settings()
    resp = JSONResponse({"status": "ok"})
    resp.delete_cookie(settings.session_cookie_name, path="/")
    return resp


# ─── 本地账号密码登录(#149,ADR-0007)— 只加不删,飞书 OIDC 保留到 P4 ──────


@router.post("/local/login")
async def local_login(
    body: LocalLoginIn,
    db: AsyncSession = Depends(get_db),  # noqa: B008  # FastAPI DI,repo 全量同款
    auth: FeishuOIDCService = Depends(get_auth_service),  # noqa: B008
    local_auth: LocalAuthService = Depends(get_local_auth),  # noqa: B008
    audit: AuditService = Depends(get_audit),  # noqa: B008
    ctx: dict[str, str | None] = Depends(get_request_context),  # noqa: B008
) -> JSONResponse:
    """账号密码登录 → 复用 encode_session 签 session JWT + set cookie。

    限流:per IP + per username 双维度 Redis 计数,失败 5 次锁 15min(#149)。
    username 不强制邮箱格式:含 @ 匹配 email,否则匹配 name(拼音/工号友好)。
    """
    settings = get_settings()
    ip = ctx.get("request_ip") or "unknown"
    username = body.username.strip()
    if not username:
        raise HTTPException(400, "用户名不能为空")

    if await local_auth.is_locked(ip, username):
        raise HTTPException(
            429,
            f"登录失败次数过多,账号已锁定 {settings.auth_lock_seconds // 60} 分钟,请稍后再试",
        )

    user = await local_auth.find_user_by_username(db, username)
    # 统一文案:用户不存在 / 未设本地密码 / 密码错误都不区分(不泄露账号存在性)
    ok = (
        user is not None
        and user.password_hash is not None
        and local_auth.verify_password(body.password, user.password_hash)
    )
    if not ok:
        await local_auth.record_failure(ip, username)
        await audit.write(
            event_type="local_login_failed",
            actor_user_id=user.id if user else None,
            request_ip=ip,
            user_agent=ctx.get("user_agent"),
            details={"username": username, "reason": "bad_credentials"},
        )
        raise HTTPException(401, "用户名或密码错误")

    assert user is not None  # ok=True 蕴含 user 存在
    if not user.is_active:
        await local_auth.record_failure(ip, username)
        await audit.write(
            event_type="local_login_failed",
            actor_user_id=user.id,
            request_ip=ip,
            user_agent=ctx.get("user_agent"),
            details={"username": username, "reason": "inactive"},
        )
        raise HTTPException(403, "用户已离职 / 被禁用,请联系管理员")

    await local_auth.reset_failures(ip, username)
    await audit.write(
        event_type="local_login_success",
        actor_user_id=user.id,
        request_ip=ip,
        user_agent=ctx.get("user_agent"),
        details={"username": username},
    )

    session_token = auth.encode_session(user)
    resp = JSONResponse({
        "status": "ok",
        "user_id": str(user.id),
        "name": user.name,
        "must_change_password": user.must_change_password,
    })
    resp.set_cookie(
        settings.session_cookie_name,
        session_token,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite=settings.session_cookie_samesite,  # type: ignore[arg-type]
        max_age=settings.session_jwt_ttl_seconds,
        path="/",
    )
    log.info("local login success user_id=%s", user.id)
    return resp


@router.post("/change-password")
async def change_password(
    body: ChangePasswordIn,
    cur: CurrentUser = Depends(get_current_user),  # noqa: B008  # FastAPI DI,repo 全量同款
    db: AsyncSession = Depends(get_db),  # noqa: B008
    local_auth: LocalAuthService = Depends(get_local_auth),  # noqa: B008
    audit: AuditService = Depends(get_audit),  # noqa: B008
    ctx: dict[str, str | None] = Depends(get_request_context),  # noqa: B008
) -> JSONResponse:
    """修改密码;首登 must_change_password=true 时前端强制走此流程(#149)。

    原密码校验通过 → 新密码过策略 → 写库 + must_change_password 置 false。
    已登录 session 不失效(stateless JWT,机制零改动)。
    """
    ip = ctx.get("request_ip") or "unknown"
    user = await db.get(User, cur.id)
    if not user:
        raise HTTPException(401, "session user not found")

    if user.password_hash is None:
        # 存量飞书用户从未设本地密码:拒绝盲改,走管理后台初始化(P2)
        raise HTTPException(400, "该账号尚未设置本地密码,请联系管理员初始化")

    if not local_auth.verify_password(body.old_password, user.password_hash):
        await audit.write(
            event_type="password_changed",
            actor_user_id=user.id,
            request_ip=ip,
            user_agent=ctx.get("user_agent"),
            details={"ok": False, "reason": "wrong_old_password"},
        )
        raise HTTPException(400, "原密码不正确")

    policy_error = local_auth.validate_password_policy(body.new_password)
    if policy_error:
        raise HTTPException(400, policy_error)
    if body.new_password == body.old_password:
        raise HTTPException(400, "新密码不能与原密码相同")

    user.password_hash = local_auth.hash_password(body.new_password)
    user.must_change_password = False
    await db.commit()

    await audit.write(
        event_type="password_changed",
        actor_user_id=user.id,
        request_ip=ip,
        user_agent=ctx.get("user_agent"),
        details={"ok": True},
    )
    log.info("password changed user_id=%s", user.id)
    return JSONResponse({"status": "ok"})
