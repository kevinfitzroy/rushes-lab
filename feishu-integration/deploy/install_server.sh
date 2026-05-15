#!/usr/bin/env bash
# 一次性服务器初始化:装 Caddy + Python venv + systemd unit。
# 在远程服务器(root)上跑;.env 需要在跑这个脚本之前手动 scp 到 /opt/feishu-poc/.env。
set -euo pipefail

APP_DIR=/opt/feishu-poc
DOMAIN=rusheslab.taoxiplan.com
EXPECTED_IP=47.109.30.236

echo "[0/6] DNS 预检"
RESOLVED=$(getent hosts "$DOMAIN" | awk '{print $1}' | head -1 || true)
if [ "$RESOLVED" != "$EXPECTED_IP" ]; then
  echo "  !! $DOMAIN 解析到 '$RESOLVED',期望 '$EXPECTED_IP'"
  echo "  !! 在 DNS 全球传播开之前启动 Caddy 会触发 ACME 反复失败 + rate limit"
  echo "  !! 解决:在阿里云加 A 记录,等 dig +short $DOMAIN @1.1.1.1 返回 $EXPECTED_IP 后再跑本脚本"
  exit 1
fi
echo "  ok: $DOMAIN -> $RESOLVED"

echo "[1/6] apt update + 基础包"
apt-get update -qq
apt-get install -y -qq python3.10-venv python3-pip curl ca-certificates debian-keyring debian-archive-keyring apt-transport-https

if ! command -v caddy >/dev/null 2>&1; then
  echo "[2/6] 安装 Caddy(官方 apt 源)"
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  apt-get update -qq
  apt-get install -y -qq caddy
else
  echo "[2/6] Caddy 已存在,跳过"
fi

echo "[3/6] Python venv + deps"
mkdir -p "$APP_DIR"
if [ ! -d "$APP_DIR/.venv" ]; then
  python3 -m venv "$APP_DIR/.venv"
fi
"$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

echo "[4/6] Caddyfile"
install -m 644 "$APP_DIR/deploy/Caddyfile" /etc/caddy/Caddyfile
systemctl reload caddy 2>/dev/null || systemctl restart caddy
systemctl enable caddy >/dev/null

echo "[5/6] systemd unit"
install -m 644 "$APP_DIR/deploy/feishu-poc.service" /etc/systemd/system/feishu-poc.service
systemctl daemon-reload
systemctl enable feishu-poc >/dev/null

if [ ! -f "$APP_DIR/.env" ]; then
  echo "[6/6] !!! /opt/feishu-poc/.env 不存在,请 scp 真实 env 后再 systemctl start feishu-poc"
  exit 0
fi

echo "[6/6] 启动 feishu-poc"
systemctl restart feishu-poc
sleep 2
systemctl status feishu-poc --no-pager | head -15 || true
echo
echo "done. 验证:"
echo "  curl -sS http://127.0.0.1:8080/healthz"
echo "  curl -sS https://rusheslab.taoxiplan.com/healthz   # DNS 通后"
