"""Presigner backend + uppy AwsS3 multipart 5-endpoint + 静态前端 serve.

ADR-0005 Phase A.2 PoC — uppy 大文件 multipart upload 链路验证(§11.2 Gap 2)。

设计:
- 单 container,同时 serve `/`(static uppy.html)和 `/s3/*`(uppy AwsS3 plugin endpoint)
- presigned URL 用 alice 凭证签(PoC 简化;真实业务用 STS / per-user key)
- 签出 URL host 是容器内 `poc-pigsty-minio:9000` → 替换为 `localhost:6100`(SSH tunnel 后浏览器视角)
"""
import http.server
import socketserver
import json
import os
import urllib.parse
from pathlib import Path

import boto3
from botocore.client import Config

# ─── config ──────────────────────────────────────────────────────────────────
MINIO_ENDPOINT_INTERNAL = os.environ.get("MINIO_ENDPOINT", "http://poc-pigsty-minio:9000")
MINIO_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY", "alice")
MINIO_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY", "alicesecret-poc-2026-32chars-pad")
# 浏览器看到的 MinIO host(SSH tunnel 后 = localhost:6100;远端直连 = 8.156.34.238:6100)
MINIO_PUBLIC_HOST = os.environ.get("MINIO_PUBLIC_HOST", "http://localhost:6100")
DEFAULT_BUCKET = os.environ.get("DEFAULT_BUCKET", "incoming")
DEFAULT_PREFIX = os.environ.get("DEFAULT_PREFIX", "uppy-test/")
URL_TTL = 3600  # 1h
STATIC_DIR = Path(__file__).parent / "static"
PORT = 8000

# ─── boto3 clients ────────────────────────────────────────────────────────────
# 两个 client:
#   - s3_internal:容器内访问 MinIO(用 docker network DNS),做 admin API 调用(create / complete / abort / list)
#   - s3_signer:签 presigned URL 用浏览器视角 host(同一签名 host 与 user agent host 必须匹配,
#     否则 sig v4 canonical request 不一致触发 SignatureDoesNotMatch)
s3_internal = boto3.client(
    "s3",
    endpoint_url=MINIO_ENDPOINT_INTERNAL,
    aws_access_key_id=MINIO_ACCESS_KEY,
    aws_secret_access_key=MINIO_SECRET_KEY,
    config=Config(signature_version="s3v4", region_name="us-east-1"),
)

# s3_signer 的 endpoint_url 是浏览器/外部 client 视角的 MinIO host;此 client 不会发请求,
# 只用 endpoint_url 构造 URL + 计算签名,所以容器内是否能访问该 host 不重要。
s3_signer = boto3.client(
    "s3",
    endpoint_url=MINIO_PUBLIC_HOST,
    aws_access_key_id=MINIO_ACCESS_KEY,
    aws_secret_access_key=MINIO_SECRET_KEY,
    config=Config(signature_version="s3v4", region_name="us-east-1"),
)


# ─── handler ──────────────────────────────────────────────────────────────────
class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "PocPresigner/1.0"

    # CORS headers,允许 uppy 浏览器跨域访问
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,DELETE,OPTIONS,PUT")
        self.send_header("Access-Control-Allow-Headers", "Content-Type,Authorization,x-requested-with")
        self.send_header("Access-Control-Expose-Headers", "ETag,Location,x-amz-version-id")

    def _json(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _err(self, code, msg):
        self._json(code, {"error": msg})

    def _read_body(self):
        n = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(n).decode() if n else "{}"
        try:
            return json.loads(raw)
        except Exception:
            return {"_raw": raw[:500]}

    def _serve_static(self, path):
        # path = '/'  ⇒  index.html;否则 path 内文件
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        f = STATIC_DIR / rel
        if not f.exists() or not f.is_file():
            return self._err(404, f"static not found: {rel}")
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".js": "application/javascript",
            ".css": "text/css",
            ".json": "application/json",
        }.get(f.suffix, "application/octet-stream")
        data = f.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self._cors()
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        print(f"[presigner] {self.command} {self.path}", flush=True)

    # ── OPTIONS preflight ─────────────────────────────────────────────────────
    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    # ── GET ───────────────────────────────────────────────────────────────────
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        p = u.path
        q = urllib.parse.parse_qs(u.query)

        # 健康检查
        if p == "/health":
            return self._json(200, {"ok": True, "minio": MINIO_PUBLIC_HOST, "bucket": DEFAULT_BUCKET})

        # uppy AwsS3 multipart: sign part — GET /s3/multipart/{uploadId}/{partNumber}?key=...
        if p.startswith("/s3/multipart/") and p.count("/") == 4:
            parts = p.split("/")
            upload_id, part_number = parts[3], int(parts[4])
            key = q.get("key", [""])[0]
            if not key or not upload_id:
                return self._err(400, "key and uploadId required")
            url = s3_signer.generate_presigned_url(
                "upload_part",
                Params={"Bucket": DEFAULT_BUCKET, "Key": key, "UploadId": upload_id, "PartNumber": part_number},
                ExpiresIn=URL_TTL,
            )
            return self._json(200, {"url": url, "expires": URL_TTL})

        # uppy AwsS3 multipart: list parts — GET /s3/multipart/{uploadId}?key=...
        if p.startswith("/s3/multipart/") and p.count("/") == 3:
            upload_id = p.split("/")[3]
            key = q.get("key", [""])[0]
            if not key or not upload_id:
                return self._err(400, "key and uploadId required")
            try:
                resp = s3_internal.list_parts(Bucket=DEFAULT_BUCKET, Key=key, UploadId=upload_id)
                out = [
                    {"PartNumber": p["PartNumber"], "Size": p["Size"], "ETag": p["ETag"]}
                    for p in resp.get("Parts", [])
                ]
                return self._json(200, out)
            except Exception as e:
                return self._err(400, str(e))

        # 静态(/, /index.html, /...)
        return self._serve_static(p)

    # ── POST ──────────────────────────────────────────────────────────────────
    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        p = u.path
        q = urllib.parse.parse_qs(u.query)

        # uppy AwsS3 multipart: create — POST /s3/multipart
        if p == "/s3/multipart":
            body = self._read_body()
            filename = body.get("filename") or "unnamed"
            content_type = body.get("type") or "application/octet-stream"
            key = DEFAULT_PREFIX + filename
            resp = s3_internal.create_multipart_upload(Bucket=DEFAULT_BUCKET, Key=key, ContentType=content_type)
            return self._json(200, {"uploadId": resp["UploadId"], "key": key})

        # uppy AwsS3 multipart: complete — POST /s3/multipart/{uploadId}/complete?key=...
        if p.startswith("/s3/multipart/") and p.endswith("/complete"):
            upload_id = p.split("/")[3]
            key = q.get("key", [""])[0]
            body = self._read_body()
            parts = body.get("parts", [])
            if not key or not upload_id or not parts:
                return self._err(400, "key, uploadId and parts required")
            try:
                resp = s3_internal.complete_multipart_upload(
                    Bucket=DEFAULT_BUCKET,
                    Key=key,
                    UploadId=upload_id,
                    MultipartUpload={"Parts": [{"PartNumber": p["PartNumber"], "ETag": p["ETag"]} for p in parts]},
                )
                return self._json(200, {"location": resp.get("Location", ""), "key": key, "etag": resp.get("ETag", "")})
            except Exception as e:
                return self._err(400, str(e))

        return self._err(404, f"unknown POST path: {p}")

    # ── DELETE ────────────────────────────────────────────────────────────────
    def do_DELETE(self):
        u = urllib.parse.urlparse(self.path)
        p = u.path
        q = urllib.parse.parse_qs(u.query)

        # uppy AwsS3 multipart: abort — DELETE /s3/multipart/{uploadId}?key=...
        if p.startswith("/s3/multipart/") and p.count("/") == 3:
            upload_id = p.split("/")[3]
            key = q.get("key", [""])[0]
            if not key or not upload_id:
                return self._err(400, "key and uploadId required")
            try:
                s3_internal.abort_multipart_upload(Bucket=DEFAULT_BUCKET, Key=key, UploadId=upload_id)
                return self._json(200, {"aborted": True})
            except Exception as e:
                return self._err(400, str(e))

        return self._err(404, f"unknown DELETE path: {p}")


class ThreadedServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


if __name__ == "__main__":
    print(f"presigner: MinIO internal={MINIO_ENDPOINT_INTERNAL} public={MINIO_PUBLIC_HOST}", flush=True)
    print(f"presigner: bucket={DEFAULT_BUCKET} prefix={DEFAULT_PREFIX}", flush=True)
    print(f"presigner: static={STATIC_DIR}", flush=True)
    print(f"presigner: listening on 0.0.0.0:{PORT}", flush=True)
    with ThreadedServer(("0.0.0.0", PORT), Handler) as httpd:
        httpd.serve_forever()
