"""admin router — 内部诊断 / 审计后台。

  GET  /api/v1/admin/audit?...              — audit 查询(分页 + filter)
  GET  /api/v1/admin/audit/export.csv?...   — audit 流式 CSV 导出

#154:飞书诊断 endpoint(/feishu/health、/feishu/test-card)随飞书下线删除(ADR-0007)。
"""
from __future__ import annotations

import csv
import io
import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.tables import AuditEvent
from app.deps import CurrentUser, require_system_admin

log = logging.getLogger(__name__)
router = APIRouter()


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
    actor_user_id: uuid.UUID | None,
    actor_open_id: str | None,
    event_type: str | None,
    project_id: uuid.UUID | None,
    from_time: datetime | None,
    to_time: datetime | None,
):
    stmt = select(AuditEvent)
    if event_type:
        stmt = stmt.where(AuditEvent.event_type == event_type)
    # #150:actor 过滤改 users.id UUID(UserPicker 语义切换);open_id 过滤保留兼容老调用
    if actor_user_id:
        stmt = stmt.where(AuditEvent.actor_user_id == actor_user_id)
    elif actor_open_id:
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
    actor_user_id: uuid.UUID | None = Query(None, description="按 actor users.id 过滤(#150)"),
    actor_open_id: str | None = Query(None, description="按 actor open_id 过滤(旧调用方)"),
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
        actor_user_id, actor_open_id, event_type, project_id, from_time, to_time,
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
    actor_user_id: uuid.UUID | None = Query(None, description="按 actor users.id 过滤(#150)"),
    actor_open_id: str | None = Query(None, description="按 actor open_id 过滤(旧调用方)"),
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
        actor_user_id, actor_open_id, event_type, project_id, from_time, to_time,
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
