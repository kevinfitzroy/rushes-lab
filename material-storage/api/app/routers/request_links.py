"""Request links router — #112 admin 生成"申请入口"短链。

  POST /api/v1/request-links              — 创建(project admin 或 system admin)
  GET  /api/v1/request-links/{token}      — 落地解析(任意登录用户)

PR-1 backend only;PR-2 加 frontend RequestLinkLandingPage + Create modal + 入口 button。

切记:link 限定 receiver_open_id 时,**enforce 必须在 backend approval 创建路径**,
不能只靠 frontend 隐藏 UI。本期暂未在 approvals 路径加 `via_link` enforce —
本 PR 标记为 PR-2 一起做(否则 link receiver 限制是假的,advisor risk #3)。
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.deps import (
    CurrentUser, get_current_user, get_is_system_admin, get_permissions,
)
from app.services.permissions import PermissionsService
from app.services.request_link import (
    DEFAULT_TTL_SECONDS, MAX_TTL_SECONDS, RequestLinkError,
    create_request_link, mark_used, resolve_request_link,
)
from app.settings import get_settings

log = logging.getLogger(__name__)
router = APIRouter()


class CreateIn(BaseModel):
    # ApprovalRequest.target_type 不支持 'folder';request_link 也对齐(schema CHECK 留
    # 'folder' 为 future flexibility,但 router 入口不开放,避免生成无法申请的链接)
    target_type: Literal["sensitive_folder", "asset", "project"]
    target_id: uuid.UUID
    allowed_actions: list[Literal["access", "download"]] = Field(
        ..., min_length=1, max_length=2,
        description="可申请的动作集;access 仅适用 sensitive_folder",
    )
    receiver_open_id: str | None = Field(
        None, description="限定只此 open_id 可用(null = 任意登录用户)",
    )
    ttl_seconds: int | None = Field(
        None, ge=60, le=MAX_TTL_SECONDS,
        description=f"有效期秒数,默认 {DEFAULT_TTL_SECONDS}s (3d), 上限 {MAX_TTL_SECONDS}s (30d)",
    )


class CreateOut(BaseModel):
    token: str
    landing_url: str
    expires_at: datetime
    allowed_actions: list[str]


class ResolveOut(BaseModel):
    token: str
    target_type: str
    target_id: uuid.UUID
    target_name: str | None
    allowed_actions: list[str]
    expires_at: datetime
    inviter_name: str | None
    # 接收者是否受限(true = link 指定了 receiver_open_id);后端会 enforce
    # 当 caller 不匹配 expected 时,前端可以直接显 "此链接不是给你的"
    receiver_restricted: bool
    receiver_match: bool


def _landing_url(token: str) -> str:
    base = get_settings().web_app_base_url.rstrip("/")
    return f"{base}/r/{token}"


@router.post("", response_model=CreateOut, status_code=201)
async def create_link(
    payload: CreateIn,
    db: AsyncSession = Depends(get_db),
    permissions: PermissionsService = Depends(get_permissions),
    user: CurrentUser = Depends(get_current_user),
    is_system_admin: bool = Depends(get_is_system_admin),
) -> CreateOut:
    """生成 request link。

    权限:system admin 或者目标资源的 project admin。
    PoC 简化:project / folder / asset / sensitive_folder 都映射到所属 project 上做 admin enforce
    (要再 audit upward — 本期假设 admin 给自己 admin 的项目下任意资源生成链接)。
    """
    # admin enforce — system admin 全直通,其他必须对 target 资源 can_admin
    # v4 model:asset/folder/sensitive_folder/project 都用 can_admin 一致 relation
    if not is_system_admin:
        ok = await permissions.check(
            user_subject=f"user:{user.open_id}",
            relation="can_admin",
            object_type=payload.target_type,
            object_id=str(payload.target_id),
        )
        if not ok:
            raise HTTPException(
                403,
                "无权对该资源生成申请链接 — 需要 system admin 或该资源 admin",
            )

    try:
        row = await create_request_link(
            db,
            inviter_user_id=user.id,
            target_type=payload.target_type,
            target_id=payload.target_id,
            allowed_actions=list(payload.allowed_actions),
            receiver_open_id=payload.receiver_open_id,
            ttl_seconds=payload.ttl_seconds,
        )
    except RequestLinkError as e:
        raise HTTPException(400, str(e)) from e

    return CreateOut(
        token=row.token,
        landing_url=_landing_url(row.token),
        expires_at=row.expires_at,
        allowed_actions=row.allowed_actions,
    )


@router.get("/{token}", response_model=ResolveOut)
async def resolve(
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> ResolveOut:
    """落地查询。任意登录 user 可访问;receiver_open_id 限制由前端结合本接口
    返回的 receiver_match 字段显示提示,实际 enforce 在 PR-2 加到 approvals 创建路径。"""
    info = await resolve_request_link(db, token)
    if info is None:
        raise HTTPException(404, "链接不存在或已过期")

    # fire-and-forget audit used_at
    await mark_used(db, token)

    expected = info["receiver_open_id"]
    receiver_restricted = bool(expected)
    receiver_match = (not receiver_restricted) or (expected == user.open_id)

    return ResolveOut(
        token=info["token"],
        target_type=info["target_type"],
        target_id=info["target_id"],
        target_name=info["target_name"],
        allowed_actions=info["allowed_actions"],
        expires_at=info["expires_at"],
        inviter_name=info["inviter_name"],
        receiver_restricted=receiver_restricted,
        receiver_match=receiver_match,
    )
