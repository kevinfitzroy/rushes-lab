"""Request link service — #112 admin 生成"申请入口"分享链接。

跟 share_service 不同:share 是凭证(链接 = 直接授权),request link 是表单(接收者
落地后走正常 approval 流程,admin IM 卡片审批后才生效)。schema 独立(advisor 决策
避免污染 share 反范式),不复用 audit_events.details。
"""
from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.tables import Asset, Folder, Project, RequestLinkToken, User

log = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 3 * 24 * 3600           # 3 天(advisor 决策)
MAX_TTL_SECONDS = 30 * 24 * 3600              # 30 天 cap
TOKEN_BYTES = 24                              # → 32 chars base64url

_VALID_TARGET_TYPES = {"sensitive_folder", "asset", "project", "folder"}
_VALID_ACTIONS = {"access", "download"}


class RequestLinkError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def create_request_link(
    db: AsyncSession,
    *,
    inviter_user_id: uuid.UUID,
    target_type: str,
    target_id: uuid.UUID,
    allowed_actions: list[str],
    receiver_open_id: str | None = None,
    ttl_seconds: int | None = None,
) -> RequestLinkToken:
    """创建 request link token。

    Raises RequestLinkError on validation fail。调用方 router enforce admin 权限。
    """
    if target_type not in _VALID_TARGET_TYPES:
        raise RequestLinkError(f"target_type must be one of {sorted(_VALID_TARGET_TYPES)}")
    if not allowed_actions:
        raise RequestLinkError("allowed_actions must not be empty")
    bad = [a for a in allowed_actions if a not in _VALID_ACTIONS]
    if bad:
        raise RequestLinkError(f"invalid action(s): {bad}")

    # action / target_type 语义约束(model):
    #   - access 仅适用 sensitive_folder
    #   - download 适用 asset / project / folder
    if "access" in allowed_actions and target_type != "sensitive_folder":
        raise RequestLinkError("action=access only valid for target_type=sensitive_folder")

    # target 存在性(避免生成指向不存在资源的死链)
    if target_type in ("sensitive_folder", "folder"):
        f = await db.get(Folder, target_id)
        if f is None:
            raise RequestLinkError("target folder not found")
    elif target_type == "asset":
        a = await db.get(Asset, target_id)
        if a is None:
            raise RequestLinkError("target asset not found")
    elif target_type == "project":
        p = await db.get(Project, target_id)
        if p is None:
            raise RequestLinkError("target project not found")

    ttl = ttl_seconds if ttl_seconds is not None else DEFAULT_TTL_SECONDS
    ttl = min(max(60, ttl), MAX_TTL_SECONDS)
    expires_at = _now() + timedelta(seconds=ttl)
    token = secrets.token_urlsafe(TOKEN_BYTES)

    row = RequestLinkToken(
        token=token,
        target_type=target_type,
        target_id=target_id,
        allowed_actions=allowed_actions,
        inviter_user_id=inviter_user_id,
        receiver_open_id=receiver_open_id,
        expires_at=expires_at,
    )
    db.add(row)
    await db.commit()
    log.info("request_link created token=%s… target=%s/%s actions=%s ttl=%ds",
             token[:6], target_type, target_id, allowed_actions, ttl)
    return row


async def resolve_request_link(
    db: AsyncSession,
    token: str,
) -> dict[str, Any] | None:
    """落地查询 token → 资源元信息 + 邀请人信息 + 可申请动作集。

    None = 不存在 / 已过期(同一处理,不泄漏存在性)。
    返:{token, target_type, target_id, target_name, allowed_actions, expires_at,
         receiver_open_id, inviter_user_id, inviter_name}
    receiver_open_id 由调用方 enforce(对比 current_user.open_id)。
    """
    row = await db.get(RequestLinkToken, token)
    if row is None:
        return None
    if row.expires_at <= _now():
        return None

    # #136/#137: 复用共享 helper(同 ApprovalOut enrich)
    from app.services.target_resolve import resolve_target_name_and_project
    target_name, _ = await resolve_target_name_and_project(db, row.target_type, row.target_id)

    inviter_name: str | None = None
    inviter = await db.get(User, row.inviter_user_id)
    if inviter:
        inviter_name = inviter.name

    return {
        "token": row.token,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "target_name": target_name,
        "allowed_actions": row.allowed_actions,
        "expires_at": row.expires_at,
        "receiver_open_id": row.receiver_open_id,
        "inviter_user_id": row.inviter_user_id,
        "inviter_name": inviter_name,
    }


async def mark_used(db: AsyncSession, token: str) -> None:
    """首次 / 后续访问都更新 used_at(便于审计)。fire-and-forget — 失败不阻塞。"""
    try:
        row = await db.get(RequestLinkToken, token)
        if row and row.used_at is None:
            row.used_at = _now()
            await db.commit()
    except Exception as e:  # noqa: BLE001
        log.warning("mark_used failed token=%s…: %s", token[:6], e)


async def check_receiver_allowed(
    link: RequestLinkToken | dict[str, Any],
    current_user_open_id: str,
) -> bool:
    """若 link 限定了 receiver_open_id,必须匹配 current user;否则任意登录 user OK。"""
    expected = link.receiver_open_id if isinstance(link, RequestLinkToken) else link["receiver_open_id"]
    if not expected:
        return True
    return expected == current_user_open_id
