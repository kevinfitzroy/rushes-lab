/**
 * 飞书 H5 JSSDK 初始化 — 检测 webview 后加载 lark-jssdk + config。
 *
 * 完整 production 流程:
 *   1. 前端检测 in-feishu (UA 含 'Lark' 或 'Feishu')
 *   2. 拿当前 URL 后端调 /api/v1/auth/feishu-jsapi-ticket 签 signature
 *      (需 ms-api 加 endpoint:用 app_access_token 调飞书 OpenAPI 取 jsapi_ticket,
 *       再 HMAC-SHA1(ticket, noncestr+timestamp+url) 出 signature)
 *   3. window.h5sdk.config({appId, signature, noncestr, timestamp})
 *   4. h5sdk.ready(() => 业务调 tt.requestAuth / tt.share 等 API)
 *
 * 当前 iter:只加载 SDK + 注入 ms-api 后端 sign endpoint 占位,
 * 实际 jsapi_ticket 签名留 iter4(需 ms-api 新加 endpoint)。
 *
 * SDK 文档:https://open.feishu.cn/document/uYjL24iN/uYDOyYjL2gjM24iN4IjN/h5-jssdk
 */

declare global {
  interface Window {
    h5sdk?: {
      config: (cfg: {
        appId: string;
        timestamp: number;
        nonceStr: string;
        signature: string;
        jsApiList?: string[];
        onSuccess?: () => void;
        onFail?: (err: unknown) => void;
      }) => void;
      ready: (cb: () => void) => void;
      error: (cb: (err: unknown) => void) => void;
    };
    tt?: Record<string, unknown>;
  }
}

const LARK_JSSDK_URL = 'https://lf-package-cn.feishucdn.com/obj/feishu-static/lark/passport/qrcode/LarkSSOSDKWebJSSDK-1-0-3.js';

let loadPromise: Promise<boolean> | null = null;

export function isFeishuWebview(): boolean {
  const ua = navigator.userAgent;
  return /Lark|Feishu/i.test(ua);
}

/** lazy 加载 jssdk script(只加载一次)。*/
function loadJsSdk(): Promise<boolean> {
  if (loadPromise) return loadPromise;
  loadPromise = new Promise((resolve) => {
    if (window.h5sdk) return resolve(true);
    const s = document.createElement('script');
    s.src = LARK_JSSDK_URL;
    s.async = true;
    s.onload = () => resolve(!!window.h5sdk);
    s.onerror = () => resolve(false);
    document.head.appendChild(s);
  });
  return loadPromise;
}

/** 主入口:webview 内调,自动加载 + config(若 backend signature 可用)。*/
export async function initFeishu(): Promise<{
  loaded: boolean;
  inWebview: boolean;
  configured: boolean;
  reason?: string;
}> {
  const inWebview = isFeishuWebview();
  if (!inWebview) return { loaded: false, inWebview: false, configured: false, reason: 'not in feishu webview' };

  const loaded = await loadJsSdk();
  if (!loaded || !window.h5sdk) return { loaded: false, inWebview, configured: false, reason: 'sdk load failed' };

  // TODO iter4:fetch /api/v1/auth/feishu-jsapi-ticket → {appId, timestamp, nonceStr, signature}
  // 当前 stub:不 config,但 SDK 已可用于 detection
  return { loaded: true, inWebview, configured: false, reason: 'config 留 iter4 实施(需 ms-api jsapi-ticket endpoint)' };
}
