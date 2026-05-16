"""webhooks router — 飞书事件统一入口。

飞书事件 / 卡片回调统一接入此 URL(飞书后台"事件订阅 Request URL"和
"消息卡片请求网址"均填同一个 `/api/v1/webhooks/feishu`):

- url_verification               — 飞书后台首次验证 challenge
- contact.user.created_v3        — 入职:upsert + 加部门 tuples
- contact.user.updated_v3        — 资料变更(含换部门)— diff dept_ids
- contact.user.deleted_v3        — 离职闭环 → revoke_user_completely
- contact.department.updated_v3  — 部门 parent 变更 → 重写 nesting
- approval_instance              — 飞书审批 instance 状态变更(iter7 真审批闭环)
- card.action.trigger            — 飞书 IM 卡片按钮点击 → dispatch

签名校验:飞书 Verification Token(应用后台 → 事件订阅)
  - Header `X-Lark-Signature` = HMAC-SHA256(verification_token, timestamp + nonce + body)
  - env=dev 跳过;非 dev 强制 enforce
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.deps import get_permissions
from app.services.contact_sync import (
    get_default_organization,
    handle_user_deleted,
    sync_department_parent,
    sync_user,
)
from app.services.feishu_card_handlers import dispatch_card_action
from app.services.permissions import PermissionsService
from app.settings import get_settings

log = logging.getLogger(__name__)
router = APIRouter()


@router.post("/feishu")
async def feishu_event(
    request: Request,
    db: AsyncSession = Depends(get_db),
    permissions: PermissionsService = Depends(get_permissions),
    x_lark_signature: str | None = Header(default=None, alias="X-Lark-Signature"),
    x_lark_request_timestamp: str | None = Header(default=None, alias="X-Lark-Request-Timestamp"),
    x_lark_request_nonce: str | None = Header(default=None, alias="X-Lark-Request-Nonce"),
) -> dict:
    raw_body = await request.body()
    settings = get_settings()

    verification_token = getattr(settings, "feishu_verification_token", None)
    if settings.env != "dev" and verification_token:
        if not _verify_signature(
            verification_token,
            x_lark_request_timestamp or "",
            x_lark_request_nonce or "",
            raw_body,
            x_lark_signature or "",
        ):
            raise HTTPException(401, "invalid feishu signature")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as e:
        raise HTTPException(400, f"invalid json: {e}") from e

    if payload.get("type") == "url_verification":
        challenge = payload.get("challenge", "")
        log.info("feishu url_verification challenge=%s", challenge)
        return {"challenge": challenge}

    header = payload.get("header") or {}
    event_type = header.get("event_type")
    event_data = payload.get("event") or {}
    log.info("feishu event_type=%s tenant=%s", event_type, header.get("tenant_key"))

    # ─── contact events ──────────────────────────────────────────────────────
    if event_type == "contact.user.created_v3":
        return await _handle_user_created(event_data, db, permissions)

    if event_type == "contact.user.updated_v3":
        return await _handle_user_updated(event_data, db, permissions)

    if event_type == "contact.user.deleted_v3":
        return await _handle_user_deleted(event_data, db, permissions)

    if event_type == "contact.department.updated_v3":
        return await _handle_department_updated(event_data, permissions)

    # ─── existing handlers ───────────────────────────────────────────────────
    if event_type == "approval_instance":
        log.info("approval_instance event(iter7 接业务):%s", event_data)
        return {"status": "ack", "todo": "iter7 wire approval_instance → internal decision"}

    if event_type == "card.action.trigger":
        result = await dispatch_card_action(event_data, request)
        return result

    log.info("feishu event unhandled type=%s", event_type)
    return {"status": "ack"}


# ─── contact handlers ────────────────────────────────────────────────────────
async def _handle_user_created(
    event: dict, db: AsyncSession, permissions: PermissionsService,
) -> dict:
    user_obj = event.get("object") or {}
    open_id = user_obj.get("open_id")
    if not open_id:
        return {"status": "ack", "warning": "no open_id"}
    org = await get_default_organization(db)
    if org is None:
        log.warning("user_created %s: no default org configured", open_id)
        return {"status": "ack", "warning": "no default org"}
    org_id, tenant_key = org
    await sync_user(
        db, permissions,
        user_obj=user_obj,
        organization_tenant_key=tenant_key,
        organization_id=org_id,
        previous_department_ids=None,   # 全量
    )
    return {"status": "ack", "open_id": open_id}


async def _handle_user_updated(
    event: dict, db: AsyncSession, permissions: PermissionsService,
) -> dict:
    user_obj = event.get("object") or {}
    open_id = user_obj.get("open_id")
    if not open_id:
        return {"status": "ack", "warning": "no open_id"}
    old_obj = event.get("old_object") or {}
    prev_deps = old_obj.get("department_ids") if old_obj else None

    org = await get_default_organization(db)
    if org is None:
        return {"status": "ack", "warning": "no default org"}
    org_id, tenant_key = org
    await sync_user(
        db, permissions,
        user_obj=user_obj,
        organization_tenant_key=tenant_key,
        organization_id=org_id,
        previous_department_ids=prev_deps,
    )
    return {"status": "ack", "open_id": open_id, "had_old": old_obj is not None}


async def _handle_user_deleted(
    event: dict, db: AsyncSession, permissions: PermissionsService,
) -> dict:
    open_id = (event.get("object") or {}).get("open_id")
    if not open_id:
        return {"status": "ack", "warning": "no open_id"}
    n = await handle_user_deleted(db, permissions, open_id=open_id)
    return {"status": "ack", "open_id": open_id, "revoked_tuples": n}


async def _handle_department_updated(
    event: dict, permissions: PermissionsService,
) -> dict:
    obj = event.get("object") or {}
    old = event.get("old_object") or {}
    dept_id = obj.get("open_department_id") or obj.get("department_id")
    if not dept_id:
        return {"status": "ack", "warning": "no department_id"}
    parent = obj.get("parent_department_id")
    prev_parent = old.get("parent_department_id")
    await sync_department_parent(
        permissions,
        department_id=dept_id,
        parent_department_id=parent,
        previous_parent_department_id=prev_parent,
    )
    return {"status": "ack", "department_id": dept_id, "parent": parent}


def _verify_signature(
    token: str, timestamp: str, nonce: str, body: bytes, expected_sig: str
) -> bool:
    """飞书签名校验:HMAC-SHA256(token, timestamp + nonce + body)。"""
    msg = (timestamp + nonce).encode() + body
    digest = hmac.new(token.encode(), msg, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, expected_sig)
