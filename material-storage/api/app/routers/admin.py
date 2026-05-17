"""admin router — 内部诊断 / 审计后台。

  GET  /api/v1/admin/feishu/health          — tenant_access_token + 注册的 card intent
  POST /api/v1/admin/feishu/test-card       — 给自己 / 指定 open_id 发测试卡
  GET  /api/v1/admin/audit?...              — audit 查询(分页 + filter)
  GET  /api/v1/admin/audit/export.csv?...   — audit 流式 CSV 导出
"""
from __future__ import annotations

import csv
import io
import logging
import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.tables import AuditEvent, User
from app.deps import CurrentUser, require_system_admin, get_feishu_client
from app.services.feishu_card_handlers import registered_intents
from app.services.feishu_cards import (
    build_approval_card,
    build_invite_card,
    build_share_card,
)
from app.services.feishu_client import FeishuAPIError, FeishuClient
from app.settings import get_settings

log = logging.getLogger(__name__)
router = APIRouter()


@router.get("/feishu/health")
async def feishu_health(
    feishu: FeishuClient = Depends(get_feishu_client),
    user: CurrentUser = Depends(require_system_admin),
) -> dict[str, object]:
    """tenant_access_token 拿不到时 token=None + error。"""
    settings = get_settings()
    out: dict[str, object] = {
        "im_enabled": settings.feishu_im_enabled,
        "open_api_base": settings.feishu_open_api_base,
        "app_id": settings.feishu_app_id,
        "registered_card_intents": registered_intents(),
    }
    if not settings.feishu_im_enabled:
        out["token"] = None
        out["note"] = "feishu_im_enabled=false — IM 推送 no-op"
        return out
    try:
        token = await feishu.get_tenant_access_token()
        out["token"] = f"{token[:8]}…(redacted)"
        out["token_ok"] = True
    except (FeishuAPIError, Exception) as e:  # noqa: BLE001
        out["token"] = None
        out["token_ok"] = False
        out["error"] = str(e)
    return out


class TestCardIn(BaseModel):
    template: Literal["approval", "share", "invite"] = "approval"
    receive_id: str | None = None  # 默认推给当前 admin 自己


@router.post("/feishu/test-card")
async def feishu_test_card(
    payload: TestCardIn,
    db: AsyncSession = Depends(get_db),
    feishu: FeishuClient = Depends(get_feishu_client),
    user: CurrentUser = Depends(require_system_admin),
) -> dict[str, object]:
    user_id, user_open_id = user.id, user.open_id
    """给指定 open_id(默认自己)推一张测试卡片。用于 iter1 验证发送链路。"""
    settings = get_settings()
    if not settings.feishu_im_enabled:
        raise HTTPException(400, "feishu_im_enabled=false")

    receive_id = payload.receive_id
    if not receive_id:
        u = await db.get(User, user_id)
        if not u or not u.feishu_open_id:
            raise HTTPException(404, "current user has no feishu_open_id")
        receive_id = u.feishu_open_id

    web = settings.web_app_base_url.rstrip("/") + "/"
    if payload.template == "approval":
        card = build_approval_card(
            applicant_name="测试用户",
            target_label="测试 folder / 测试.mp4",
            action_label="临时下载 1h",
            reason="iter1 验证卡片基础设施 — 这是一张测试卡片",
            approval_id="00000000-0000-0000-0000-000000000000",
            web_url=web,
        )
    elif payload.template == "share":
        card = build_share_card(
            sharer_name="测试用户",
            resource_label="测试.mp4(127.3 MB)",
            resource_type="asset",
            open_url=web + "share/__test__",
            expires_label="24 小时",
            message="iter1 验证卡片基础设施",
        )
    else:  # invite
        card = build_invite_card(
            inviter_name="测试用户",
            target_label="测试项目",
            target_type="project",
            role_label="editor",
            open_url=web + "projects/__test__",
            duration_label=None,
        )

    try:
        data = await feishu.send_im_card(receive_id, card, receive_id_type="open_id")
    except FeishuAPIError as e:
        # 把飞书完整 error body 透传给调用方,便于定位权限/参数问题
        raise HTTPException(
            502,
            {"feishu_code": e.code, "feishu_msg": e.msg,
             "feishu_error": e.raw.get("error"),
             "hint": "权限问题去 https://open.feishu.cn/app/<app_id>/auth 申请"},
        ) from e
    return {"ok": True, "receive_id": receive_id, "message_id": data.get("message_id"),
            "template": payload.template}


# ─── audit query ─────────────────────────────────────────────────────────────
class AuditOut(BaseModel):
    id: str
    event_type: str
    event_time: datetime
    actor_user_id: str | None
    actor_name: str | None
    actor_open_id: str | None
    target_asset_id: str | None
    target_project_id: str | None
    target_minio_key: str | None
    request_ip: str | None
    details: dict


def _build_audit_query(
    actor_open_id: str | None,
    event_type: str | None,
    project_id: uuid.UUID | None,
    from_time: datetime | None,
    to_time: datetime | None,
):
    stmt = select(AuditEvent)
    if event_type:
        stmt = stmt.where(AuditEvent.event_type == event_type)
    if actor_open_id:
        stmt = stmt.where(AuditEvent.actor_open_id_snapshot == actor_open_id)
    if project_id:
        stmt = stmt.where(AuditEvent.target_project_id == project_id)
    if from_time:
        stmt = stmt.where(AuditEvent.event_time >= from_time)
    if to_time:
        stmt = stmt.where(AuditEvent.event_time <= to_time)
    return stmt


@router.get("/audit", response_model=list[AuditOut])
async def list_audit(
    actor_open_id: str | None = Query(None, description="按 actor open_id 过滤"),
    event_type: str | None = Query(None, description="精确 event_type 过滤"),
    project_id: uuid.UUID | None = Query(None),
    from_time: datetime | None = Query(None, alias="from"),
    to_time: datetime | None = Query(None, alias="to"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_system_admin),
) -> list[AuditOut]:
    """audit 查询(分页 + filter)— 仅 system admin。"""
    _ = user.id
    stmt = _build_audit_query(
        actor_open_id, event_type, project_id, from_time, to_time,
    ).order_by(AuditEvent.event_time.desc()).limit(limit).offset(offset)
    res = await db.execute(stmt)
    return [
        AuditOut(
            id=str(e.id),
            event_type=e.event_type,
            event_time=e.event_time,
            actor_user_id=str(e.actor_user_id) if e.actor_user_id else None,
            actor_name=e.actor_name_snapshot,
            actor_open_id=e.actor_open_id_snapshot,
            target_asset_id=str(e.target_asset_id) if e.target_asset_id else None,
            target_project_id=str(e.target_project_id) if e.target_project_id else None,
            target_minio_key=e.target_minio_key,
            request_ip=e.request_ip,
            details=e.details or {},
        )
        for e in res.scalars().all()
    ]


@router.get("/audit/export.csv")
async def export_audit_csv(
    actor_open_id: str | None = Query(None),
    event_type: str | None = Query(None),
    project_id: uuid.UUID | None = Query(None),
    from_time: datetime | None = Query(None, alias="from"),
    to_time: datetime | None = Query(None, alias="to"),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_system_admin),
) -> StreamingResponse:
    """流式 CSV 导出(同 query filter)— UTF-8 BOM 给 Excel 兼容。"""
    _ = user.id
    stmt = _build_audit_query(
        actor_open_id, event_type, project_id, from_time, to_time,
    ).order_by(AuditEvent.event_time.desc()).limit(50000)

    async def gen():
        buf = io.StringIO()
        writer = csv.writer(buf)
        # BOM for Excel
        yield "﻿".encode()
        writer.writerow([
            "time", "event_type", "actor_name", "actor_open_id",
            "target_project_id", "target_asset_id", "target_minio_key",
            "request_ip", "details_json",
        ])
        yield buf.getvalue().encode()
        buf.seek(0); buf.truncate()

        import json as _json
        res = await db.execute(stmt)
        for e in res.scalars().all():
            writer.writerow([
                e.event_time.isoformat() if e.event_time else "",
                e.event_type,
                e.actor_name_snapshot or "",
                e.actor_open_id_snapshot or "",
                str(e.target_project_id) if e.target_project_id else "",
                str(e.target_asset_id) if e.target_asset_id else "",
                e.target_minio_key or "",
                e.request_ip or "",
                _json.dumps(e.details or {}, ensure_ascii=False),
            ])
            chunk = buf.getvalue().encode()
            if chunk:
                yield chunk
                buf.seek(0); buf.truncate()

    filename = f"audit-{datetime.now().strftime('%Y%m%d-%H%M%S')}.csv"
    return StreamingResponse(
        gen(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
