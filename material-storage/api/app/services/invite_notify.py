"""邀请 IM 卡片推送 — iter4。

场景:
- folders.invite POST /api/v1/folders/{id}/invite — admin 直接邀请 user 进 sensitive_folder
  → 推 IM 卡给被邀请 user(group 邀请跳过,group 没有 feishu_open_id)
- D iter4 之后会有 project member 邀请 endpoint,hook 模式相同(notify_project_member_invite)

设计:
- best-effort,失败仅 log + audit
- BG task wrapper 自开 db session
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.tables import Folder, Project, User
from app.services.audit import AuditService
from app.services.feishu_cards import build_invite_card
from app.services.feishu_client import FeishuAPIError, FeishuClient
from app.settings import Settings

log = logging.getLogger(__name__)


async def notify_folder_invite(
    *,
    folder_id: uuid.UUID,
    invitee_user_id: uuid.UUID,
    inviter_user_id: uuid.UUID,
    duration_seconds: int | None,
    db: AsyncSession,
    feishu: FeishuClient,
    audit: AuditService,
    settings: Settings,
) -> None:
    if not settings.feishu_im_enabled:
        return

    invitee = await db.get(User, invitee_user_id)
    if invitee is None or not invitee.feishu_open_id or not invitee.is_active:
        log.info("notify_folder_invite: invitee %s no feishu_open_id / inactive — skip",
                 invitee_user_id)
        return

    folder = await db.get(Folder, folder_id)
    if folder is None:
        log.warning("notify_folder_invite: folder %s not found", folder_id)
        return
    project = await db.get(Project, folder.project_id)
    inviter = await db.get(User, inviter_user_id)

    target_label = f"{project.name if project else '?'} / {folder.name}"
    open_url = _web_url(settings, "projects", str(folder.project_id),
                        "folders", str(folder_id))
    duration_label = _duration_label(duration_seconds) if duration_seconds else None

    card = build_invite_card(
        inviter_name=inviter.name if inviter else "(未知)",
        target_label=target_label,
        target_type="sensitive_folder",
        role_label="敏感目录成员",
        open_url=open_url,
        duration_label=duration_label,
    )

    message_id: str | None = None
    err: str | None = None
    try:
        data = await feishu.send_im_card(
            invitee.feishu_open_id, card, receive_id_type="open_id"
        )
        message_id = data.get("message_id")
    except FeishuAPIError as e:
        log.warning("notify_folder_invite feishu fail folder=%s invitee=%s code=%s msg=%s",
                    folder_id, invitee_user_id, e.code, e.msg)
        err = f"{e.code}:{e.msg[:120]}"
    except Exception as e:  # noqa: BLE001
        log.warning("notify_folder_invite unexpected fail folder=%s invitee=%s err=%s",
                    folder_id, invitee_user_id, e)
        err = str(e)[:120]

    await audit.write(
        event_type="invite_notified",
        actor_user_id=inviter_user_id,
        details={
            "scope": "sensitive_folder",
            "folder_id": str(folder_id),
            "invitee_user_id": str(invitee_user_id),
            "invitee_open_id": invitee.feishu_open_id,
            "permanent": duration_seconds is None,
            "duration_seconds": duration_seconds,
            "message_id": message_id,
            "error": err,
        },
    )


async def run_notify_folder_invite_bg(
    *,
    folder_id: uuid.UUID,
    invitee_user_id: uuid.UUID,
    inviter_user_id: uuid.UUID,
    duration_seconds: int | None,
    feishu: FeishuClient,
    settings: Settings,
) -> None:
    from app.db.session import get_sessionmaker
    try:
        async with get_sessionmaker()() as db:
            audit = AuditService(db)
            await notify_folder_invite(
                folder_id=folder_id,
                invitee_user_id=invitee_user_id,
                inviter_user_id=inviter_user_id,
                duration_seconds=duration_seconds,
                db=db, feishu=feishu, audit=audit, settings=settings,
            )
    except Exception:  # noqa: BLE001
        log.exception("run_notify_folder_invite_bg failed folder=%s invitee=%s",
                      folder_id, invitee_user_id)


# ─── helpers ──────────────────────────────────────────────────────────────────
def _web_url(settings: Settings, *parts: str) -> str:
    base = settings.web_app_base_url.rstrip("/") + "/"
    return base + "/".join(p.strip("/") for p in parts)


def _duration_label(seconds: int) -> str:
    if seconds < 3600:
        return f"{max(1, seconds // 60)} 分钟"
    if seconds < 86400:
        h = seconds / 3600
        return f"{int(h)} 小时" if h.is_integer() else f"{h:.1f} 小时"
    d = seconds / 86400
    return f"{int(d)} 天" if d.is_integer() else f"{d:.1f} 天"
