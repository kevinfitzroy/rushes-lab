#!/usr/bin/env bash
# 一键部署 ms-api 到 server2 (8.156.34.238) + bootstrap + e2e + 大文件测试。
#
# 用法(必须在 material-storage/api 目录下):
#   SSH_PASS='12qwaszxA@@@666!!!' bash scripts/deploy_server2.sh
# 或:
#   ! cd /Users/foxer/claude/rushes-lab-workspace/rushes-lab/material-storage/api && SSH_PASS='12qwaszxA@@@666!!!' bash scripts/deploy_server2.sh
set -euo pipefail

HOST="${HOST:-8.156.34.238}"
USER="${USER:-root}"
PASS="${SSH_PASS:?need SSH_PASS env}"
REMOTE_DIR="/root/material-storage-api"

GREEN='\033[0;32m'; YEL='\033[0;33m'; NC='\033[0m'
step() { echo -e "\n${YEL}═══${NC} $* ${YEL}═══${NC}"; }
ok() { echo -e "${GREEN}✓${NC} $*"; }

ssh_run() { sshpass -p "$PASS" ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "$USER@$HOST" "$@"; }
scp_to() { sshpass -p "$PASS" scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -r "$@"; }
rsync_to() { sshpass -p "$PASS" rsync -az -e "ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null" "$@"; }

step "0) 检查本地环境(在 material-storage/api 目录运行)"
[[ -f Dockerfile ]] || { echo "ERROR: 必须在 material-storage/api/ 下跑"; exit 1; }
ok "本地 ms-api 目录已确认"

step "1) rsync 源码到 server2:$REMOTE_DIR"
ssh_run "mkdir -p $REMOTE_DIR"
rsync_to --exclude='__pycache__' --exclude='.pytest_cache' --exclude='.venv' \
  --exclude='.env' --exclude='tests/__pycache__' \
  ./ "$USER@$HOST:$REMOTE_DIR/"
ok "代码已同步"

step "2) 生成 server2 上的 .env"
ssh_run "cat > $REMOTE_DIR/.env" <<'EOF'
ENV=dev
LOG_LEVEL=INFO
LOG_FORMAT=console

DB_URL=postgresql+asyncpg://msuser:mspass@ms-db:5432/material_storage
REDIS_URL=redis://ms-redis:6379/0

MINIO_ENDPOINT_INTERNAL=http://poc-pigsty-minio:9000
MINIO_ENDPOINT_PUBLIC=https://rusheslab.taoxiplan.com
MINIO_ACCESS_KEY=alice
MINIO_SECRET_KEY=alicesecret-poc-2026-32chars-pad
MINIO_DEFAULT_BUCKET=ms-dev

OPENFGA_API_URL=http://poc-openfga:8080
OPENFGA_STORE_ID=__WILL_FILL__

FEISHU_APP_ID=cli_aa8c58fae5391be7
FEISHU_APP_SECRET=2T1QWnYdm2ayq0t4ByANNcIXEUFHwFMw
FEISHU_REDIRECT_URI=https://rusheslab.taoxiplan.com/api/v1/auth/callback
FEISHU_VERIFICATION_TOKEN=03HkZIjvHJyRmaV922Rkac0wJ7zedQuE

SESSION_JWT_SECRET=dev-secret-do-not-use-in-prod-replace-with-openssl-rand-hex-32
SESSION_COOKIE_SECURE=false
SESSION_COOKIE_SAMESITE=lax
EOF
ok ".env 写入"

step "3) 找 OpenFGA store_id 并填进 .env"
STORE_ID=$(ssh_run "docker exec poc-openfga grpcurl -plaintext localhost:8081 openfga.v1.OpenFGAService/ListStores 2>/dev/null | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d[\"stores\"][0][\"id\"])' 2>/dev/null || curl -sS http://127.0.0.1:8089/stores | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d[\"stores\"][0][\"id\"])'")
echo "STORE_ID=$STORE_ID"
ssh_run "sed -i 's|__WILL_FILL__|$STORE_ID|' $REMOTE_DIR/.env"
ok "OPENFGA_STORE_ID 写入"

step "4) docker compose build + up"
ssh_run "cd $REMOTE_DIR && docker compose up -d --build ms-db ms-redis ms-api 2>&1 | tail -20"
sleep 5
ssh_run "docker ps --filter name=ms- --format 'table {{.Names}}\t{{.Status}}'"
ok "ms-api 起来了"

step "5) alembic migrate"
ssh_run "cd $REMOTE_DIR && docker compose exec -T ms-api alembic upgrade head 2>&1 | tail -10"
ok "DB migration done"

step "6) dev bootstrap"
ssh_run "cd $REMOTE_DIR && docker compose exec -T ms-api python -m scripts.dev_bootstrap 2>&1 | tail -15"
ok "bootstrap done"

step "7) e2e test"
ssh_run "cd $REMOTE_DIR && API_BASE=http://localhost:8200 bash scripts/e2e_test.sh 2>&1" | tail -80
ok "e2e ok"

step "8) 500MB 大文件 multipart 测试"
ssh_run "cd $REMOTE_DIR && API_BASE=http://localhost:8200 SIZE_MB=500 bash scripts/large_file_upload.sh 2>&1" | tail -40
ok "large file upload ok"

step "9) 检查 ms-api 通过 nginx 外网可达"
ssh_run "curl -sS http://localhost/api/v1 2>&1 | head -3 || echo 'nginx 还没配 /api 路由'"
echo
echo -e "${GREEN}══════ 全部部署 + 测试完成 ══════${NC}"
echo "uppy demo: 在 server2 nginx 加 /api → 127.0.0.1:8200 + /static → 同;或本地 SSH tunnel:"
echo "  ssh -L 8200:127.0.0.1:8200 root@$HOST"
echo "  然后浏览器开 http://localhost:8200/static/uppy.html"
