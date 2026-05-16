"""admin router — 内部诊断 / 调试 endpoint。

iter1 飞书 IM 卡片基础设施验证用:
  GET  /api/v1/admin/feishu/health          — tenant_access_token 是否能拿到 + 注册的 card intent 列表
  POST /api/v1/admin/feishu/test-card       — 给自己 / 指定 open_id 发一张测试卡(approval 模板)
"""
from __future__ import annotations

import logging
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.tables import User
from app.deps import get_current_user_id, get_feishu_client
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
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> dict[str, object]:
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
        raise HTTPException(502, f"feishu api error: code={e.code} msg={e.msg}") from e
    return {"ok": True, "receive_id": receive_id, "message_id": data.get("message_id"),
            "template": payload.template}
