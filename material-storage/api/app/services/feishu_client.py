"""飞书 OpenAPI 客户端 — IM 卡片推送 + tenant_access_token 缓存。

封装:
- tenant_access_token 自动获取 + 内存缓存(按 expire 时间 refresh,带异步锁防并发)
- send_im_card / update_im_card — interactive 卡片推送 / 更新
- send_text — 备用文本消息(降级 fallback 或 debug)
- batch_send_im_card — 多接收人(逐个调,飞书 batch API 需 mass send,这里走简单 fan-out)

依赖:lark-oapi 在 pyproject.toml 但本模块直接走 httpx,SDK 略重不引;
若以后要 lark-oapi 的 long-connect callback 模式再切换。

引用:
- https://open.feishu.cn/document/server-docs/authentication-management/access-token/tenant_access_token_internal
- https://open.feishu.cn/document/server-docs/im-v1/message/create
- https://open.feishu.cn/document/server-docs/im-v1/message-card/patch
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Literal

import httpx

from app.settings import Settings

log = logging.getLogger(__name__)

ReceiveIdType = Literal["open_id", "union_id", "user_id", "email", "chat_id"]


class FeishuAPIError(RuntimeError):
    """飞书 OpenAPI 返回 code != 0。"""

    def __init__(self, code: int, msg: str, raw: dict[str, Any]):
        super().__init__(f"feishu api error code={code} msg={msg}")
        self.code = code
        self.msg = msg
        self.raw = raw


class FeishuClient:
    """飞书 OpenAPI httpx wrapper(单例,挂 app.state.feishu_client)。"""

    # tenant_access_token 提前 N 秒 refresh,避免边界过期
    _REFRESH_MARGIN_SECONDS = 300

    def __init__(self, settings: Settings):
        self._settings = settings
        self._http = httpx.AsyncClient(
            base_url=settings.feishu_open_api_base.rstrip("/"),
            timeout=httpx.Timeout(connect=5.0, read=10.0, write=10.0, pool=5.0),
        )
        self._token: str | None = None
        self._token_expire_ts: float = 0.0
        self._token_lock = asyncio.Lock()

    async def close(self) -> None:
        await self._http.aclose()

    # ─── tenant_access_token ─────────────────────────────────────────────────
    async def get_tenant_access_token(self) -> str:
        """获取 tenant_access_token,内存缓存 + 异步锁防并发重复请求。"""
        now = time.time()
        if self._token and now < self._token_expire_ts - self._REFRESH_MARGIN_SECONDS:
            return self._token

        async with self._token_lock:
            # double-check after lock
            now = time.time()
            if self._token and now < self._token_expire_ts - self._REFRESH_MARGIN_SECONDS:
                return self._token

            resp = await self._http.post(
                "/open-apis/auth/v3/tenant_access_token/internal",
                json={
                    "app_id": self._settings.feishu_app_id,
                    "app_secret": self._settings.feishu_app_secret,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            code = data.get("code")
            if code != 0:
                raise FeishuAPIError(code, data.get("msg", ""), data)
            self._token = data["tenant_access_token"]
            self._token_expire_ts = time.time() + data.get("expire", 7200)
            log.info("feishu tenant_access_token refreshed, expire_in=%ss", data.get("expire"))
            assert self._token is not None  # for mypy
            return self._token

    async def _auth_headers(self) -> dict[str, str]:
        token = await self.get_tenant_access_token()
        return {"Authorization": f"Bearer {token}"}

    # ─── IM 卡片 ──────────────────────────────────────────────────────────────
    async def send_im_card(
        self,
        receive_id: str,
        card: dict[str, Any],
        *,
        receive_id_type: ReceiveIdType = "open_id",
        uuid: str | None = None,
    ) -> dict[str, Any]:
        """发送 interactive(卡片)消息。

        返回飞书完整 data 段(含 message_id,可用于后续 update);
        失败抛 FeishuAPIError。

        uuid: 客户端去重 token,飞书 24h 内同 uuid 不重复发(幂等)。
        """
        body: dict[str, Any] = {
            "receive_id": receive_id,
            "msg_type": "interactive",
            "content": json.dumps(card, ensure_ascii=False),
        }
        if uuid:
            body["uuid"] = uuid

        resp = await self._http.post(
            "/open-apis/im/v1/messages",
            params={"receive_id_type": receive_id_type},
            json=body,
            headers=await self._auth_headers(),
        )
        return self._raise_or_data(resp)

    async def update_im_card(self, message_id: str, card: dict[str, Any]) -> dict[str, Any]:
        """更新已发送的 interactive 卡片(按钮已点后改文案)。

        飞书 PATCH /open-apis/im/v1/messages/{message_id}
        body: {"content": "<json string of card>"}
        """
        resp = await self._http.patch(
            f"/open-apis/im/v1/messages/{message_id}",
            json={"content": json.dumps(card, ensure_ascii=False)},
            headers=await self._auth_headers(),
        )
        return self._raise_or_data(resp)

    async def send_text(
        self,
        receive_id: str,
        text: str,
        *,
        receive_id_type: ReceiveIdType = "open_id",
    ) -> dict[str, Any]:
        """发文本消息,用于卡片 fallback / debug。"""
        resp = await self._http.post(
            "/open-apis/im/v1/messages",
            params={"receive_id_type": receive_id_type},
            json={
                "receive_id": receive_id,
                "msg_type": "text",
                "content": json.dumps({"text": text}, ensure_ascii=False),
            },
            headers=await self._auth_headers(),
        )
        return self._raise_or_data(resp)

    async def batch_send_im_card(
        self,
        receive_ids: list[str],
        card: dict[str, Any],
        *,
        receive_id_type: ReceiveIdType = "open_id",
    ) -> list[tuple[str, str | None, str | None]]:
        """fan-out 多接收人(逐个调);返 [(receive_id, message_id|None, err|None)]。

        飞书有 batch_send API 但需 chat / group,这里走简单 ID 列表 fan-out。
        失败不抛,记进结果列表 — 调用方决定是否告警。
        """
        results: list[tuple[str, str | None, str | None]] = []
        for rid in receive_ids:
            try:
                data = await self.send_im_card(rid, card, receive_id_type=receive_id_type)
                results.append((rid, data.get("message_id"), None))
            except (FeishuAPIError, httpx.HTTPError) as e:
                log.warning("send_im_card fail receive_id=%s err=%s", rid, e)
                results.append((rid, None, str(e)))
        return results

    # ─── internals ───────────────────────────────────────────────────────────
    def _raise_or_data(self, resp: httpx.Response) -> dict[str, Any]:
        resp.raise_for_status()
        body = resp.json()
        if body.get("code") != 0:
            raise FeishuAPIError(body.get("code", -1), body.get("msg", ""), body)
        return body.get("data") or {}


async def create_feishu_client(settings: Settings) -> FeishuClient:
    """lifespan 调用,提前 warm token(失败不挂 app,只 log warning)。"""
    client = FeishuClient(settings)
    if settings.feishu_im_enabled:
        try:
            await client.get_tenant_access_token()
        except (FeishuAPIError, httpx.HTTPError) as e:
            log.warning("feishu tenant_access_token warm failed: %s — IM 推送会在调用时重试", e)
    return client
