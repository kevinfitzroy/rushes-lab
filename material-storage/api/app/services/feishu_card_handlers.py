"""飞书卡片按钮回调 dispatcher。

飞书"消息卡片请求网址"(同事件订阅同 URL,header.event_type=card.action.trigger)
统一进 webhooks.py 入口,这里负责按 `action.value.intent` 分发到具体 handler。

iter1 只搭框架:dispatch_card_action() + 注册 noop handler;
具体 intent handler 在 iter2(approval_decision)/iter4(invite_*)实施。

按钮 value 约定 schema(builder 同步):
    {"intent": "<approval_decision|...>", ...payload}

handler 返回值:可选 dict — 若飞书要求"更新原卡片",返
    {"toast": {"type":"success","content":"..."}, "card": {<new card JSON>}}
否则返 {} / None,飞书侧不更新。
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Request

log = logging.getLogger(__name__)


# handler signature: (event, request) → optional response dict
CardActionHandler = Callable[[dict[str, Any], Request], Awaitable[dict[str, Any] | None]]

_HANDLERS: dict[str, CardActionHandler] = {}


def register_card_action(intent: str) -> Callable[[CardActionHandler], CardActionHandler]:
    """装饰器:注册 intent → handler 映射。

    用法:
        @register_card_action("approval_decision")
        async def _handle_approval(event, request):
            ...
    """

    def deco(fn: CardActionHandler) -> CardActionHandler:
        if intent in _HANDLERS:
            log.warning("card action intent %r already registered, overwriting", intent)
        _HANDLERS[intent] = fn
        return fn

    return deco


async def dispatch_card_action(event: dict[str, Any], request: Request) -> dict[str, Any]:
    """根据 event.action.value.intent 分发。

    event 形如(飞书 schema 2.0 → ms-api 解析后传入):
      {
        "operator": {"open_id":"ou_xxx", "user_id":"...", "tenant_key":"..."},
        "token": "<card token,用于异步 update>",
        "action": {
          "value": {"intent":"approval_decision", "approval_id":"...", "decision":"approve"},
          "tag": "button",
          "name": "..."
        },
        "context": {"open_message_id":"om_xxx"},
        "delivery_type": "card"
      }
    """
    action = event.get("action") or {}
    value = action.get("value") or {}
    intent = value.get("intent")

    if not intent:
        log.info("card action without intent — ignore, value=%r", value)
        return {"toast": {"type": "info", "content": "未识别的卡片操作"}}

    handler = _HANDLERS.get(intent)
    if handler is None:
        log.warning("no handler for card action intent=%r registered handlers=%r",
                    intent, list(_HANDLERS))
        return {"toast": {"type": "error", "content": f"未注册的操作:{intent}"}}

    try:
        result = await handler(event, request)
        return result or {}
    except Exception as e:  # noqa: BLE001 — 边界 catch:飞书侧需 always ack
        log.exception("card action handler %r failed: %s", intent, e)
        return {"toast": {"type": "error", "content": f"处理失败:{e}"}}


def registered_intents() -> list[str]:
    """debug / health 用,返回当前注册的 intent 列表。"""
    return sorted(_HANDLERS.keys())


# iter1 stub handler — 占位,iter2 实际接 approval
@register_card_action("__noop__")
async def _noop(event: dict[str, Any], request: Request) -> dict[str, Any] | None:
    log.info("noop card action: %r", event)
    return {"toast": {"type": "info", "content": "noop"}}
