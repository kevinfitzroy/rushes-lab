"""资源分享短链服务 — iter3 最小版。

设计:
- 不引 share_links 表(避免 alembic migration);token 存进 audit_events.details
  event_type='share_link_created',details = {kind, target_id, token, expires_at, requires_login, sharer_user_id}
- audit 表 JSONB 字段可用 PG `->>'token' = X` 反查;PoC 量级全表扫无碍,
  量起来再加 share_links 表 + token unique index(iter 后续)
- 短链 token = secrets.token_urlsafe(24) ≈ 32 char,碰撞可忽略
- requires_login=True 默认;访问 GET /share/{token} 必须有 session cookie

资源类型:
- asset  → 返 download_url(presigned)+ asset metadata
- folder → 返 folder metadata + asset 列表;web 端渲染目录页

后续 iter:max_uses + used_count + 撤销 — 都要正式表;先不做。
"""
from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.tables import Asset, AuditEvent, Folder, Project, User
from app.services.audit import AuditService
from app.services.feishu_cards import build_share_card
from app.services.feishu_client import FeishuAPIError, FeishuClient
from app.settings import Settings

log = logging.getLogger(__name__)

ShareKind = Literal["asset", "folder"]


# ─── 创建短链 ─────────────────────────────────────────────────────────────────
async def create_share(
    *,
    audit: AuditService,
    kind: ShareKind,
    target_id: uuid.UUID,
    sharer_user_id: uuid.UUID,
    expires_in_seconds: int,
    requires_login: bool = True,
) -> dict[str, Any]:
    """生成短链 token + 写 audit;不查 target 存在性(调用方 router 自己 enforce)。"""
    token = secrets.token_urlsafe(24)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in_seconds)
    await audit.write(
        event_type="share_link_created",
        actor_user_id=sharer_user_id,
        target_asset_id=target_id if kind == "asset" else None,
        details={
            "kind": kind,
            "target_id": str(target_id),
            "token": token,
            "expires_at": expires_at.isoformat(),
            "requires_login": requires_login,
            "sharer_user_id": str(sharer_user_id),
        },
    )
    return {"token": token, "expires_at": expires_at}


# ─── 解析短链 ─────────────────────────────────────────────────────────────────
async def resolve_share(db: AsyncSession, token: str) -> dict[str, Any] | None:
    """从 audit_events 反查 token;返 dict 或 None(失效/不存在)。

    返:{kind, target_id, expires_at, requires_login, sharer_user_id, sharer_name}
    """
    stmt = (
        select(AuditEvent)
        .where(AuditEvent.event_type == "share_link_created")
        .where(AuditEvent.details["token"].astext == token)
        .order_by(AuditEvent.event_time.desc())
        .limit(1)
    )
    res = await db.execute(stmt)
    event = res.scalar_one_or_none()
    if event is None:
        return None
    details = event.details or {}
    expires_at_str = details.get("expires_at")
    if not expires_at_str:
        return None
    expires_at = datetime.fromisoformat(expires_at_str)
    if expires_at < datetime.now(timezone.utc):
        return None  # 过期

    sharer_user_id = details.get("sharer_user_id")
    sharer_name = None
    if sharer_user_id:
        try:
            su = await db.get(User, uuid.UUID(sharer_user_id))
            sharer_name = su.name if su else None
        except (ValueError, TypeError):
            pass

    return {
        "kind": details.get("kind"),
        "target_id": uuid.UUID(details["target_id"]),
        "expires_at": expires_at,
        "requires_login": bool(details.get("requires_login", True)),
        "sharer_user_id": sharer_user_id,
        "sharer_name": sharer_name,
    }


# ─── 推 IM 卡片 ───────────────────────────────────────────────────────────────
async def send_share_cards(
    *,
    feishu: FeishuClient,
    settings: Settings,
    sharer_name: str,
    resource_label: str,
    resource_type: ShareKind,
    token: str,
    expires_at: datetime,
    receive_open_ids: list[str],
    message: str | None = None,
) -> list[dict[str, Any]]:
    """fan-out 发卡;失败不抛,记录在返回列表。"""
    if not settings.feishu_im_enabled or not receive_open_ids:
        return []
    open_url = _share_landing_url(settings, token)
    expires_label = _expires_label(expires_at)
    card = build_share_card(
        sharer_name=sharer_name,
        resource_label=resource_label,
        resource_type=resource_type,
        open_url=open_url,
        expires_label=expires_label,
        message=message,
    )
    sent: list[dict[str, Any]] = []
    for open_id in receive_open_ids:
        try:
            data = await feishu.send_im_card(open_id, card, receive_id_type="open_id")
            sent.append({"open_id": open_id, "message_id": data.get("message_id")})
        except FeishuAPIError as e:
            log.warning("share send fail open_id=%s code=%s msg=%s", open_id, e.code, e.msg)
            sent.append({"open_id": open_id, "error": f"{e.code}:{e.msg[:120]}"})
        except Exception as e:  # noqa: BLE001
            log.warning("share send unexpected fail open_id=%s err=%s", open_id, e)
            sent.append({"open_id": open_id, "error": str(e)[:120]})
    return sent


# ─── target label(asset / folder)─────────────────────────────────────────────
async def get_resource_label(
    db: AsyncSession, kind: ShareKind, target_id: uuid.UUID
) -> str:
    if kind == "asset":
        asset = await db.get(Asset, target_id)
        if asset is None:
            return f"asset:{target_id}"
        return f"{asset.filename} ({_humanize_bytes(asset.size_bytes)})"
    folder = await db.get(Folder, target_id)
    if folder is None:
        return f"folder:{target_id}"
    project = await db.get(Project, folder.project_id)
    return f"{project.name if project else '?'} / {folder.name}"


# ─── helpers ──────────────────────────────────────────────────────────────────
def _share_landing_url(settings: Settings, token: str) -> str:
    base = settings.web_app_base_url.rstrip("/") + "/"
    return f"{base}s/{token}"


def _expires_label(expires_at: datetime) -> str:
    delta = expires_at - datetime.now(timezone.utc)
    seconds = max(0, int(delta.total_seconds()))
    if seconds < 3600:
        return f"{max(1, seconds // 60)} 分钟"
    if seconds < 86400:
        h = seconds / 3600
        return f"{int(h)} 小时" if h.is_integer() else f"{h:.1f} 小时"
    d = seconds / 86400
    return f"{int(d)} 天" if d.is_integer() else f"{d:.1f} 天"


def _humanize_bytes(n: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    f = float(n)
    while f >= 1024 and i < len(units) - 1:
        f /= 1024
        i += 1
    return f"{f:.1f} {units[i]}" if i > 0 else f"{int(f)} {units[i]}"
