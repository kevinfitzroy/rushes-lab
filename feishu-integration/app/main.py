"""feishu-integration: 连通性 PoC。

只验证三件事:
1. 飞书 APP_ID/SECRET 能换到 tenant_access_token(启动期一次性 + /healthz)
2. 飞书事件回调 URL verification 握手(POST /api/lark/callback)能通
3. ENCRYPT_KEY / VERIFICATION_TOKEN 解密 + 校验真实事件 payload 能通

不实现任何业务逻辑(approval 申请、webhook 转发等),那是契约落地阶段的事。
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
log = logging.getLogger("feishu-poc")

APP_ID = os.environ["FEISHU_APP_ID"]
APP_SECRET = os.environ["FEISHU_APP_SECRET"]
ENCRYPT_KEY = os.environ.get("FEISHU_ENCRYPT_KEY", "")
VERIFICATION_TOKEN = os.environ["FEISHU_VERIFICATION_TOKEN"]

TENANT_TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"


@dataclass
class CachedToken:
    value: str
    expires_at: float


_token_cache: CachedToken | None = None


async def get_tenant_access_token(force_refresh: bool = False) -> CachedToken:
    """单进程内存缓存版本。生产实施会换 Redis(见 research §5.2),
    PoC 阶段只验证 APP_ID/SECRET 可换到 token,内存缓存足够。"""
    global _token_cache
    now = time.time()
    if (
        not force_refresh
        and _token_cache is not None
        and _token_cache.expires_at - now > 60
    ):
        return _token_cache

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            TENANT_TOKEN_URL,
            json={"app_id": APP_ID, "app_secret": APP_SECRET},
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        resp.raise_for_status()
        data = resp.json()

    if data.get("code") != 0:
        raise RuntimeError(f"feishu token refresh failed: {data}")

    _token_cache = CachedToken(
        value=data["tenant_access_token"],
        expires_at=now + int(data["expire"]),
    )
    log.info(
        "tenant_access_token refreshed: prefix=%s expires_in=%ss",
        _token_cache.value[:6],
        data["expire"],
    )
    return _token_cache


def _decrypt(encrypt: str, key: str) -> dict[str, Any]:
    """飞书事件加密:AES-256-CBC,key = sha256(ENCRYPT_KEY),IV = ciphertext[:16]."""
    if not key:
        raise RuntimeError("ENCRYPT_KEY not configured but encrypted event received")
    raw = base64.b64decode(encrypt)
    aes_key = hashlib.sha256(key.encode("utf-8")).digest()
    iv, ct = raw[:16], raw[16:]
    cipher = Cipher(algorithms.AES(aes_key), modes.CBC(iv))
    decryptor = cipher.decryptor()
    padded = decryptor.update(ct) + decryptor.finalize()
    pad_len = padded[-1]
    plain = padded[:-pad_len]
    return json.loads(plain.decode("utf-8"))


app = FastAPI(title="feishu-integration PoC", version="0.0.1")


@app.on_event("startup")
async def _startup() -> None:
    log.info("PoC starting; APP_ID=%s ENCRYPT_KEY=%s", APP_ID, bool(ENCRYPT_KEY))
    try:
        await get_tenant_access_token(force_refresh=True)
    except Exception as exc:
        log.exception("startup token refresh failed (continuing): %s", exc)


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    """绿/红判定:绿 = 能换到 tenant_access_token。"""
    try:
        token = await get_tenant_access_token()
        return {
            "ok": True,
            "app_id": APP_ID,
            "token_prefix": token.value[:6],
            "token_expires_in": int(token.expires_at - time.time()),
        }
    except Exception as exc:
        log.exception("healthz token check failed")
        return JSONResponse(
            status_code=503,
            content={"ok": False, "error": str(exc)},
        )


@app.post("/api/lark/callback")
async def feishu_callback(request: Request) -> Any:
    """飞书事件回调入口。

    处理两种 payload:
    1. URL verification 握手:`{"type":"url_verification","challenge":"...","token":"..."}`
       (加密时外层是 `{"encrypt":"..."}`,解密后才是上述结构)
       → 必须 200 返回 `{"challenge":"..."}`,飞书后台保存才能通过
    2. 真实事件(本 PoC 只做"收到 + log + 返回 200",不做业务处理)
    """
    body = await request.body()
    try:
        outer = json.loads(body)
    except json.JSONDecodeError:
        log.warning("callback: non-json body, len=%d", len(body))
        raise HTTPException(status_code=400, detail="invalid json")

    if "encrypt" in outer:
        try:
            payload = _decrypt(outer["encrypt"], ENCRYPT_KEY)
        except Exception as exc:
            log.exception("decrypt failed")
            raise HTTPException(status_code=400, detail=f"decrypt failed: {exc}")
    else:
        payload = outer

    log.info("callback payload keys=%s", sorted(payload.keys()))

    # URL verification (旧 v1 schema:顶层有 type / challenge / token)
    if payload.get("type") == "url_verification":
        token = payload.get("token", "")
        if token != VERIFICATION_TOKEN:
            log.warning(
                "url_verification token mismatch: got=%s... expected=%s...",
                token[:6], VERIFICATION_TOKEN[:6],
            )
            raise HTTPException(status_code=401, detail="verification token mismatch")
        challenge = payload.get("challenge", "")
        log.info("url_verification OK, returning challenge")
        return {"challenge": challenge}

    # 真实事件(v2 schema 走 header.token,v1 走顶层 token);PoC 不做业务,只 log
    header = payload.get("header") or {}
    event_type = header.get("event_type") or payload.get("event", {}).get("type")
    log.info("event received: type=%s payload=%s", event_type, json.dumps(payload)[:400])
    return {"code": 0, "msg": "received"}


@app.get("/login/callback")
async def oauth_callback_placeholder(code: str = "", state: str = "") -> dict[str, Any]:
    """OAuth 回调占位。PoC 不实现 code→token 换取,只回 200 让飞书后台保存配置不报错。"""
    log.info("oauth callback hit: code=%s... state=%s", code[:6], state[:6])
    return {"ok": True, "note": "PoC placeholder; not exchanging code for token yet"}
