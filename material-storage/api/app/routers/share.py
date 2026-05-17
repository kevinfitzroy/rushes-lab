"""share router — 资源分享短链 + 飞书 IM 卡片推送(iter3 最小版)。

endpoints:
  POST /api/v1/share/assets/{asset_id}   — 创建 asset 分享 + 推 IM 卡;需 can_download
  POST /api/v1/share/folders/{folder_id} — 创建 folder 分享 + 推 IM 卡;需 can_view
  GET  /api/v1/share/{token}             — 解析短链 → 返资源 metadata + presigned URL

短链 token 存 audit_events.details(iter3 最小版,不引新表);
GET endpoint 必须有 session cookie(短链默认 requires_login=True);
不登录 → 401(前端 SPA 跳 OIDC login + next=当前 URL)。
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.tables import Asset, Folder, User
from app.deps import (
    get_audit,
    CurrentUser,
    get_current_user,
    get_feishu_client,
    get_is_system_admin,
    get_permissions,
    get_presign,
    get_request_context,
)
from app.services.audit import AuditService
from app.services.feishu_client import FeishuClient
from app.services.permissions import PermissionsService
from app.services.presign import PresignService
from app.services.share_service import (
    create_share,
    get_resource_label,
    resolve_share,
    send_share_cards,
)
from app.settings import get_settings

log = logging.getLogger(__name__)
router = APIRouter()


# ─── input / output models ────────────────────────────────────────────────────
class ShareCreateIn(BaseModel):
    receive_open_ids: list[str] = Field(default_factory=list, max_length=20,
                                         description="接收方飞书 open_id 列表,留空 = 只生成链接不推卡")
    message: str | None = Field(None, max_length=500)
    expires_in_seconds: int = Field(86400, ge=60, le=30 * 86400,
                                     description="链接有效期;60s ~ 30 天")
    requires_login: bool = Field(True, description="True = 访问短链必须登录(默认)")


class ShareCreateOut(BaseModel):
    token: str
    landing_url: str
    expires_at: str
    sent: list[dict]


class ShareResolveOut(BaseModel):
    kind: str           # asset / folder
    target_id: uuid.UUID
    sharer_name: str | None
    expires_at: str
    # asset 专属
    asset: dict | None = None
    download_url: str | None = None
    download_expires_in: int | None = None
    # folder 专属
    folder: dict | None = None


# ─── POST share asset ─────────────────────────────────────────────────────────
@router.post("/assets/{asset_id}", response_model=ShareCreateOut)
async def share_asset(
    asset_id: uuid.UUID,
    payload: ShareCreateIn,
    db: AsyncSession = Depends(get_db),
    permissions: PermissionsService = Depends(get_permissions),
    audit: AuditService = Depends(get_audit),
    feishu: FeishuClient = Depends(get_feishu_client),
    user: CurrentUser = Depends(get_current_user),
    is_system_admin: bool = Depends(get_is_system_admin),
    ctx: dict = Depends(get_request_context),
) -> ShareCreateOut:
    user_id, user_open_id = user.id, user.open_id
    asset = await db.get(Asset, asset_id)
    if asset is None or asset.deleted_at is not None:
        raise HTTPException(404, "asset not found")

    # 分享者必须 can_download 该 asset;系统 admin 直通
    allowed = is_system_admin or await permissions.check(
        user_subject=f"user:{user_open_id}", relation="can_download",
        object_type="asset", object_id=str(asset_id),
    )
    if not allowed:
        await audit.write(
            event_type="access_denied",
            actor_user_id=user_id, target_asset_id=asset_id,
            details={"action": "share_asset", "reason": "openfga can_download false"},
            **ctx,
        )
        raise HTTPException(403, "no permission to share(需 can_download)")

    info = await create_share(
        audit=audit, kind="asset", target_id=asset_id,
        sharer_user_id=user_id,
        expires_in_seconds=payload.expires_in_seconds,
        requires_login=payload.requires_login,
    )

    sharer = await db.get(User, user_id)
    resource_label = await get_resource_label(db, "asset", asset_id)
    settings = get_settings()
    sent = await send_share_cards(
        feishu=feishu, settings=settings,
        sharer_name=sharer.name if sharer else "(未知)",
        resource_label=resource_label, resource_type="asset",
        token=info["token"], expires_at=info["expires_at"],
        receive_open_ids=payload.receive_open_ids, message=payload.message,
    )
    return ShareCreateOut(
        token=info["token"],
        landing_url=_landing_url(settings, info["token"]),
        expires_at=info["expires_at"].isoformat(),
        sent=sent,
    )


# ─── POST share folder ────────────────────────────────────────────────────────
@router.post("/folders/{folder_id}", response_model=ShareCreateOut)
async def share_folder(
    folder_id: uuid.UUID,
    payload: ShareCreateIn,
    db: AsyncSession = Depends(get_db),
    permissions: PermissionsService = Depends(get_permissions),
    audit: AuditService = Depends(get_audit),
    feishu: FeishuClient = Depends(get_feishu_client),
    user: CurrentUser = Depends(get_current_user),
    is_system_admin: bool = Depends(get_is_system_admin),
    ctx: dict = Depends(get_request_context),
) -> ShareCreateOut:
    user_id, user_open_id = user.id, user.open_id
    folder = await db.get(Folder, folder_id)
    if folder is None:
        raise HTTPException(404, "folder not found")

    object_type = "sensitive_folder" if folder.is_sensitive else "folder"
    # 系统 admin 直通
    allowed = is_system_admin or await permissions.check(
        user_subject=f"user:{user_open_id}", relation="can_view",
        object_type=object_type, object_id=str(folder_id),
    )
    if not allowed:
        await audit.write(
            event_type="access_denied",
            actor_user_id=user_id,
            details={"action": "share_folder", "folder_id": str(folder_id),
                     "reason": "openfga can_view false"},
            **ctx,
        )
        raise HTTPException(403, "no permission to share(需 can_view)")

    info = await create_share(
        audit=audit, kind="folder", target_id=folder_id,
        sharer_user_id=user_id,
        expires_in_seconds=payload.expires_in_seconds,
        requires_login=payload.requires_login,
    )
    sharer = await db.get(User, user_id)
    resource_label = await get_resource_label(db, "folder", folder_id)
    settings = get_settings()
    sent = await send_share_cards(
        feishu=feishu, settings=settings,
        sharer_name=sharer.name if sharer else "(未知)",
        resource_label=resource_label, resource_type="folder",
        token=info["token"], expires_at=info["expires_at"],
        receive_open_ids=payload.receive_open_ids, message=payload.message,
    )
    return ShareCreateOut(
        token=info["token"],
        landing_url=_landing_url(settings, info["token"]),
        expires_at=info["expires_at"].isoformat(),
        sent=sent,
    )


# ─── GET resolve ──────────────────────────────────────────────────────────────
@router.get("/{token}", response_model=ShareResolveOut)
async def resolve(
    token: str,
    db: AsyncSession = Depends(get_db),
    permissions: PermissionsService = Depends(get_permissions),
    presign: PresignService = Depends(get_presign),
    audit: AuditService = Depends(get_audit),
    user: CurrentUser = Depends(get_current_user),
    ctx: dict = Depends(get_request_context),
) -> ShareResolveOut:
    user_id, user_open_id = user.id, user.open_id
    """解析短链 → 返 metadata + presigned download_url(asset)。

    minimal 版:始终 require login(get_current_user 401 时前端 SPA 引导 OIDC)。
    """
    info = await resolve_share(db, token)
    if info is None:
        raise HTTPException(404, "share link expired or not found")

    kind = info["kind"]
    target_id: uuid.UUID = info["target_id"]
    settings = get_settings()

    if kind == "asset":
        asset = await db.get(Asset, target_id)
        if asset is None or asset.deleted_at is not None:
            raise HTTPException(404, "asset deleted")

        # 短链豁免 enforce — share owner 已 verified can_download;
        # 但落 audit 记录每次访问(谁、什么时间)
        await audit.write(
            event_type="share_link_accessed",
            actor_user_id=user_id, target_asset_id=target_id,
            details={"token": token[:6] + "…", "kind": "asset"},
            **ctx,
        )
        ttl = settings.presigned_normal_ttl_seconds
        url = presign.sign_get_url(asset.minio_bucket, asset.minio_key, ttl)
        return ShareResolveOut(
            kind="asset", target_id=target_id,
            sharer_name=info["sharer_name"],
            expires_at=info["expires_at"].isoformat(),
            asset={
                "id": str(asset.id), "filename": asset.filename,
                "size_bytes": asset.size_bytes, "content_type": asset.content_type,
            },
            download_url=url, download_expires_in=ttl,
        )

    # folder
    folder = await db.get(Folder, target_id)
    if folder is None:
        raise HTTPException(404, "folder deleted")
    await audit.write(
        event_type="share_link_accessed",
        actor_user_id=user_id,
        details={"token": token[:6] + "…", "kind": "folder",
                 "folder_id": str(target_id)},
        **ctx,
    )
    return ShareResolveOut(
        kind="folder", target_id=target_id,
        sharer_name=info["sharer_name"],
        expires_at=info["expires_at"].isoformat(),
        folder={
            "id": str(folder.id),
            "project_id": str(folder.project_id),
            "name": folder.name,
            "is_sensitive": folder.is_sensitive,
        },
    )


def _landing_url(settings, token: str) -> str:
    base = settings.web_app_base_url.rstrip("/") + "/"
    return f"{base}s/{token}"
