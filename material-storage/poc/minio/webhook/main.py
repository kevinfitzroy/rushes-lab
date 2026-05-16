"""PoC webhook receiver — 接 MinIO bucket notification,落内存 + 打 stdout(docker logs 看)。

仅用于 Phase A PoC 链路验证(ADR-0005 §11.2 Gap 9)。
用 Python stdlib,**无外部依赖**,避免 pip install 拉远程镜像源(F-X 教训:阿里云 docker hub 慢)。
真实 material-storage 后端应该用 FastAPI + 验签 + 幂等 + 异步 worker pool。
"""
import http.server
import socketserver
import json
from datetime import datetime, timezone

EVENTS = []


class Handler(http.server.BaseHTTPRequestHandler):
    def _json(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(n).decode("utf-8", errors="replace") if n else "{}"
        try:
            body = json.loads(raw)
        except Exception:
            body = {"_raw": raw[:500]}
        ts = datetime.now(timezone.utc).isoformat()
        EVENTS.append({"ts": ts, "body": body})
        rec = (body.get("Records") or [{}])[0]
        event = rec.get("eventName", "?")
        s3 = rec.get("s3", {})
        bucket = (s3.get("bucket") or {}).get("name", "?")
        key = (s3.get("object") or {}).get("key", "?")
        size = (s3.get("object") or {}).get("size", 0)
        print(f"[{ts}] {event} bucket={bucket} key={key} size={size}", flush=True)
        self._json(200, {"ok": True, "n": len(EVENTS)})

    def do_GET(self):
        if self.path == "/health":
            self._json(200, {"ok": True, "events_received": len(EVENTS)})
        elif self.path == "/events":
            self._json(200, {"events": EVENTS[-20:], "total": len(EVENTS)})
        else:
            self._json(404, {"error": "not found"})

    def log_message(self, *args):
        # 屏蔽默认 access log,只保留我们 print 的业务日志
        pass


class ThreadedServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


if __name__ == "__main__":
    PORT = 8000
    print(f"webhook listening on 0.0.0.0:{PORT}", flush=True)
    with ThreadedServer(("0.0.0.0", PORT), Handler) as httpd:
        httpd.serve_forever()
