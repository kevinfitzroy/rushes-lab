"""webhooks router — 飞书事件统一入口(Phase B-2 iter6 框架)。

飞书事件类型(iter6 框架处理 + iter7 接具体业务):
- url_verification               — 飞书后台首次验证 challenge
- contact.user.deleted_v3        — 离职闭环 → permissions.revoke_user_completely
- approval_instance              — 审批结果 → 对应 internal approve/reject

签名校验:飞书 Encrypt Key + Verification Token(后台配)
  - Header `X-Lark-Signature` = HMAC-SHA256(verification_token, timestamp + nonce + body)
  - iter6 占位 verify(env=dev 跳过);iter7 严格 enforce
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

    # ─── 1) signature verify(prod enforce)──────────────────────────────────
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

    # ─── 2) URL 验证 challenge(飞书后台 webhook 注册时)─────────────────────
    if payload.get("type") == "url_verification":
        challenge = payload.get("challenge", "")
        log.info("feishu url_verification challenge=%s", challenge)
        return {"challenge": challenge}

    # 飞书新版 v2 事件结构:{"schema": "2.0", "header": {...}, "event": {...}}
    header = payload.get("header") or {}
    event_type = header.get("event_type")
    event_data = payload.get("event") or {}
    log.info("feishu event_type=%s tenant=%s", event_type, header.get("tenant_key"))

    # ─── 3) 路由具体事件 ─────────────────────────────────────────────────────
    if event_type == "contact.user.deleted_v3":
        return await _handle_user_deleted(event_data, permissions)

    if event_type == "approval_instance":
        # iter7:approval_instance.status 转换 → 调 internal approve/reject
        log.info("approval_instance event(iter7 接业务):%s", event_data)
        return {"status": "ack", "todo": "iter7 wire approval_instance → internal decision"}

    # 未识别事件:ack 防止飞书重试,iter7 按需扩展
    log.info("feishu event unhandled type=%s", event_type)
    return {"status": "ack"}


async def _handle_user_deleted(event: dict, permissions: PermissionsService) -> dict:
    """contact.user.deleted_v3 → OpenFGA 删该 user 所有 tuple。

    event payload:
      {"object": {"open_id": "ou_xxx", "user_id": "...", "union_id": "..."}}
    """
    open_id = (event.get("object") or {}).get("open_id")
    if not open_id:
        return {"status": "ack", "warning": "no open_id in event"}

    # 注:OpenFGA tuple 用 open_id?还是 internal user_id?
    # iter5 我们 user.id (UUID) 作 OpenFGA user 主键 → 这里需要 db lookup
    # iter7 加 lookup + revoke;此处先 log
    log.warning("contact.user.deleted_v3 open_id=%s — iter7 接 db lookup + revoke_user_completely",
                open_id)
    return {"status": "ack", "todo": "iter7 db lookup + revoke"}


def _verify_signature(
    token: str, timestamp: str, nonce: str, body: bytes, expected_sig: str
) -> bool:
    """飞书签名校验:HMAC-SHA256(token, timestamp + nonce + body)。"""
    msg = (timestamp + nonce).encode() + body
    digest = hmac.new(token.encode(), msg, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, expected_sig)
