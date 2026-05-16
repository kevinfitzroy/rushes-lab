"""Audit service — Phase B-2。

写 audit_events 表;ADR-0005 §11.2 Gap 10 / PR #30 修订版。

约定:
- dedup_key 跨系统幂等;格式 <source>:<source_event_id>[:<status>]
  自产事件用 internal:<uuid>(stub key)
- actor snapshot 列冗余记(user 删后审计仍可读)
- trace_id 跨 sidecar 链统一(MinIO event → ffmpeg → dataset B → AI)
"""
from __future__ import annotations

import logging
import urllib.parse
import uuid as uuid_lib
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.tables import AuditEvent, User

log = logging.getLogger(__name__)


class AuditService:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def _resolve_actor_snapshot(self, actor_user_id: uuid_lib.UUID | None) -> dict[str, Any]:
        if not actor_user_id:
            return {}
        user = await self._session.get(User, actor_user_id)
        if not user:
            return {}
        return {
            "actor_open_id_snapshot": user.feishu_open_id,
            "actor_name_snapshot": user.name,
            "actor_email_snapshot": user.email,
        }

    async def write(
        self,
        *,
        event_type: str,
        actor_user_id: uuid_lib.UUID | None = None,
        target_asset_id: uuid_lib.UUID | None = None,
        target_project_id: uuid_lib.UUID | None = None,
        target_minio_key: str | None = None,
        dedup_key: str | None = None,
        trace_id: uuid_lib.UUID | None = None,
        request_ip: str | None = None,
        user_agent: str | None = None,
        details: dict[str, Any] | None = None,
        event_time: datetime | None = None,
    ) -> AuditEvent:
        actor_snapshot = await self._resolve_actor_snapshot(actor_user_id)
        record = {
            "id": uuid_lib.uuid4(),
            "event_type": event_type,
            "actor_user_id": actor_user_id,
            **actor_snapshot,
            "target_asset_id": target_asset_id,
            "target_project_id": target_project_id,
            "target_minio_key": target_minio_key,
            "dedup_key": dedup_key or f"internal:{uuid_lib.uuid4()}",
            "trace_id": trace_id,
            "request_ip": request_ip,
            "user_agent": user_agent,
            "details": details or {},
            "event_time": event_time or datetime.now(timezone.utc),
        }
        # ON CONFLICT(dedup_key)DO NOTHING — 重投幂等
        stmt = pg_insert(AuditEvent).values(**record).on_conflict_do_nothing(
            index_elements=["dedup_key"]
        )
        await self._session.execute(stmt)
        # audit 是 fire-and-forget:get_audit 给我们独立 session,这里独立 commit
        # 否则 session.close() 时事务回滚,event 丢失(历史 systemic bug, iter3 修)
        await self._session.commit()
        return AuditEvent(**record)

    async def upload(self, **kwargs: Any) -> AuditEvent:
        return await self.write(event_type="upload", **kwargs)

    async def download(self, **kwargs: Any) -> AuditEvent:
        return await self.write(event_type="download", **kwargs)

    async def signed_url_issued(self, **kwargs: Any) -> AuditEvent:
        return await self.write(event_type="signed_url_issued", **kwargs)

    async def proxy_download(self, **kwargs: Any) -> AuditEvent:
        return await self.write(event_type="proxy_download", **kwargs)

    async def approval_state_changed(
        self,
        *,
        approval_id: str,
        previous_status: str,
        current_status: str,
        decided_by_open_id: str | None,
        feishu_event_id: str,
        details: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> AuditEvent:
        merged_details = {
            "approval_id": approval_id,
            "previous_status": previous_status,
            "current_status": current_status,
            "decided_by_open_id": decided_by_open_id,
            **(details or {}),
        }
        return await self.write(
            event_type="approval_state_changed",
            dedup_key=f"feishu:{feishu_event_id}:{current_status}",
            details=merged_details,
            **kwargs,
        )


def decode_minio_event_key(key: str) -> str:
    """MinIO bucket notification key URL-encoded(`/` → `%2F`),P-11。"""
    return urllib.parse.unquote(key)


def mint_trace_id() -> uuid_lib.UUID:
    return uuid_lib.uuid4()
