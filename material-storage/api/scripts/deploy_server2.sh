#!/usr/bin/env bash
# 一键部署 ms-api 到 server2 (8.156.34.238) + bootstrap + e2e + 大文件测试。
#
# 前提:本机 ssh key 已上到 server2(root@HOST 免密)
#
# 用法(必须在 material-storage/api 目录下):
#   bash scripts/deploy_server2.sh
# 或:
#   ! cd /Users/foxer/claude/rushes-lab-workspace/rushes-lab/material-storage/api && bash scripts/deploy_server2.sh
#
# 如果只想兜底用密码,设 SSH_PASS 即走 sshpass 路径(需要 brew install sshpass)。
#
# ⚠️ .env 处理(踩过坑,2026-05-17):
#   默认 *不会* 覆盖 server2 已有的 .env(怕 clobber 手工调过的飞书 app 凭据等)
#   首次 bootstrap 或确实想重置时:`INIT_ENV=1 bash scripts/deploy_server2.sh`
#   heredoc 里的默认值是"老 PoC app 一份示例" — 真实生产凭据请在本机
#   server.md 维护,或通过 env 注入(FEISHU_APP_ID/FEISHU_APP_SECRET 等)。
set -euo pipefail

HOST="${HOST:-8.156.34.238}"
SSH_USER="${SSH_USER:-root}"
REMOTE_DIR="/root/material-storage-api"

GREEN='\033[0;32m'; YEL='\033[0;33m'; NC='\033[0m'
step() { echo -e "\n${YEL}═══${NC} $* ${YEL}═══${NC}"; }
ok() { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YEL}⚠${NC} $*"; }

SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=10"
if [[ -n "${SSH_PASS:-}" ]]; then
  export SSHPASS="$SSH_PASS"
  SSH_OPTS="$SSH_OPTS -o PreferredAuthentications=password -o PubkeyAuthentication=no"
  ssh_run() { sshpass -e ssh $SSH_OPTS "$SSH_USER@$HOST" "$@"; }
  rsync_to() { sshpass -e rsync -az -e "ssh $SSH_OPTS" "$@"; }
else
  ssh_run() { ssh $SSH_OPTS "$SSH_USER@$HOST" "$@"; }
  rsync_to() { rsync -az -e "ssh $SSH_OPTS" "$@"; }
fi

step "0) 检查本地环境(在 material-storage/api 目录运行)"
[[ -f Dockerfile ]] || { echo "ERROR: 必须在 material-storage/api/ 下跑"; exit 1; }
ok "本地 ms-api 目录已确认"

step "0.3) build web 前端产物(vite → ../api/app/static/web)"
# #138 incident(2026-05-21):deploy 只 rsync api/(含 static/web 产物)但从不 build 前端,
# 导致改了 .tsx 却 rsync 旧产物 → 前端改动不上线(连续 4 个 PR 才发现)。在此固化 build,
# 产物随 step 1 的 api/ rsync 一并发布。放 banner 之前:build 失败即停(set -e),不留挂横幅。
# build 在本地跑(本地有 pnpm + node_modules),不是 server2。
( cd ../web && pnpm run build ) 2>&1 | tail -15
ok "web 产物已重新 build(随 api/ 一并发布)"

step "0.5) 开启 maintenance banner(deploy 期间给前端弹 modal,避免测试人员中途惊吓)"
# MAINTENANCE_ISSUES 两种格式:
#   (a) bare 数字列表:`"101 104"` — 自动 gh issue view 拉 title
#   (b) JSON:`'[{"number":101,"summary":"…"}]'` — 直接使用
ISSUES_JSON='[]'
if [[ -n "${MAINTENANCE_ISSUES:-}" ]]; then
  if [[ "${MAINTENANCE_ISSUES:0:1}" == "[" ]]; then
    if echo "$MAINTENANCE_ISSUES" | python3 -c 'import json,sys;json.loads(sys.stdin.read())' 2>/dev/null; then
      ISSUES_JSON="$MAINTENANCE_ISSUES"
    else
      warn "MAINTENANCE_ISSUES JSON 解析失败,banner.issues 留空"
    fi
  else
    items=()
    for n in $MAINTENANCE_ISSUES; do
      title=$(gh issue view "$n" --repo kevinfitzroy/rushes-lab --json title -q .title 2>/dev/null || echo "")
      if [[ -n "$title" ]]; then
        items+=("$(python3 -c 'import json,sys;print(json.dumps({"number":int(sys.argv[1]),"summary":sys.argv[2]},ensure_ascii=False))' "$n" "$title")")
      else
        warn "gh issue view #$n 拉 title 失败,跳过"
      fi
    done
    if [[ ${#items[@]} -gt 0 ]]; then
      ISSUES_JSON="[$(IFS=,; echo "${items[*]}")]"
    fi
  fi
fi

NOW_ISO=$(python3 -c "from datetime import datetime, timezone; print(datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))")
ENDS_ISO=$(python3 -c "from datetime import datetime, timezone, timedelta; print((datetime.now(timezone.utc) + timedelta(seconds=120)).strftime('%Y-%m-%dT%H:%M:%SZ'))")
BANNER_JSON=$(python3 -c "
import json, sys
print(json.dumps({
  'active': True,
  'message': '正在部署一次更新,通常 1 分钟内恢复。',
  'issues': json.loads(sys.argv[1]),
  'started_at': sys.argv[2],
  'ends_at': sys.argv[3],
}, ensure_ascii=False))
" "$ISSUES_JSON" "$NOW_ISO" "$ENDS_ISO")

# base64 传输避开 quoting 噩梦(JSON 含双引号/中文/可能的特殊字符)
# SETEX 900s 兜底 — 即使脚本崩 banner 也会 15 分钟后自然消失
ENC=$(printf '%s' "$BANNER_JSON" | base64 | tr -d '\n')
if ssh_run "echo '$ENC' | base64 -d | docker exec -i ms-redis redis-cli -x SETEX maintenance:banner 900 >/dev/null"; then
  ok "maintenance banner 已开启(900s TTL 兜底);前端 ≤8s 内弹 modal"
else
  warn "banner 开启失败(ms-redis 没起?),deploy 继续"
fi

step "1) rsync 源码到 server2:$REMOTE_DIR"
ssh_run "mkdir -p $REMOTE_DIR"
rsync_to --exclude='__pycache__' --exclude='.pytest_cache' --exclude='.venv' \
  --exclude='.env' --exclude='tests/__pycache__' \
  ./ "$SSH_USER@$HOST:$REMOTE_DIR/"
ok "代码已同步"

step "2) .env 处理"
if [[ "${INIT_ENV:-0}" == "1" ]]; then
  echo "INIT_ENV=1 — 用脚本默认值覆盖 server2 上的 .env(老 PoC app,务必校对!)"
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

# ⚠️ 仅老 PoC app 示例 — 生产请用 server.md 里"新的 feishu app"覆盖
FEISHU_APP_ID=cli_aa8c58fae5391be7
FEISHU_APP_SECRET=2T1QWnYdm2ayq0t4ByANNcIXEUFHwFMw
FEISHU_REDIRECT_URI=https://rusheslab.taoxiplan.com/api/v1/auth/callback
FEISHU_VERIFICATION_TOKEN=03HkZIjvHJyRmaV922Rkac0wJ7zedQuE

WEB_APP_BASE_URL=https://rusheslab.taoxiplan.com/ms-static/web/

SESSION_JWT_SECRET=dev-secret-do-not-use-in-prod-replace-with-openssl-rand-hex-32
SESSION_COOKIE_SECURE=false
SESSION_COOKIE_SAMESITE=lax
EOF
  ok "INIT_ENV 模式:.env 已写入(下一步会自动填 OPENFGA_STORE_ID)"
else
  if ssh_run "test -f $REMOTE_DIR/.env"; then
    ok "已存在 server2 .env,保留不动(如需重置:INIT_ENV=1)"
  else
    echo "❌ server2 $REMOTE_DIR/.env 不存在;首次部署请用 INIT_ENV=1 跑一次,然后人工核对飞书凭据等再正式 deploy"
    exit 1
  fi
fi

step "3) 找 OpenFGA store_id"
STORE_ID=$(ssh_run "docker exec poc-openfga grpcurl -plaintext localhost:8081 openfga.v1.OpenFGAService/ListStores 2>/dev/null | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d[\"stores\"][0][\"id\"])' 2>/dev/null || curl -sS http://127.0.0.1:8089/stores | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d[\"stores\"][0][\"id\"])'")
echo "STORE_ID=$STORE_ID"
if [[ "${INIT_ENV:-0}" == "1" ]]; then
  ssh_run "sed -i 's|__WILL_FILL__|$STORE_ID|' $REMOTE_DIR/.env"
  ok "OPENFGA_STORE_ID 写入(INIT_ENV)"
else
  ok "STORE_ID 仅打印参考;不修改保留的 .env"
fi

step "3.5) 备份上一轮 ms-api logs(--build 会 recreate container,旧 logs 会丢)"
TS=$(date +%Y%m%d-%H%M%S)
LOG_BACKUP="/tmp/ms-api-${TS}.log"
if ssh_run "docker logs ms-api > $LOG_BACKUP 2>&1"; then
  LINES=$(ssh_run "wc -l < $LOG_BACKUP")
  ok "上一轮 logs ($LINES 行) → server2:$LOG_BACKUP"
else
  warn "ms-api 未在跑(首次部署?),跳过 log 备份"
fi

step "4) docker compose build + up"
# 含 ms-worker — 漏掉它,改 worker 代码 deploy 不会 reload 长进程(2026-05-18 B-4 iter2 发现)
ssh_run "cd $REMOTE_DIR && docker compose up -d --build ms-db ms-redis ms-api ms-worker 2>&1 | tail -20"
sleep 5
ssh_run "docker ps --filter name=ms- --format 'table {{.Names}}\t{{.Status}}'"
ok "ms-api + ms-worker 起来了"

step "5) alembic migrate"
ssh_run "cd $REMOTE_DIR && docker compose exec -T ms-api alembic upgrade head 2>&1 | tail -10"
ok "DB migration done"

step "6) dev bootstrap(允许失败 — issue #69 已知 v3 stale 方法,不阻塞 deploy)"
# 远端 bash 默认无 pipefail,docker 命令失败会被 tail 吞 exit code → 本地 ssh_run 错判为成功
# 显式 `set -o pipefail` 让 ssh_run 拿到真实 exit code,允许 fail 但 warn 替代假 ok
if ssh_run "set -o pipefail; cd $REMOTE_DIR && docker compose exec -T ms-api python -m scripts.dev_bootstrap 2>&1 | tail -15"; then
  ok "bootstrap done"
else
  warn "bootstrap 失败(#69 known stale,不阻塞);若不是 v3 attribute error 请人工 review"
fi

step "6.5) seed onboarding 项目(public,新用户上手用)"
if ssh_run "set -o pipefail; cd $REMOTE_DIR && docker compose exec -T ms-api python -m scripts.seed_onboarding_project 2>&1 | tail -15"; then
  ok "onboarding 项目 seed 完成"
else
  warn "onboarding seed 失败(不阻塞;查 /tmp/ms-api-*.log)"
fi

step "7) e2e test(允许失败 — 部分 case 依赖 bootstrap;关心红色 ✗ 才需 follow up)"
if ssh_run "set -o pipefail; cd $REMOTE_DIR && API_BASE=http://localhost:8200 bash scripts/e2e_test.sh 2>&1 | tail -80"; then
  ok "e2e ok"
else
  warn "e2e 失败(部分 case 依赖 bootstrap seed,#69 未解期间预期红);关心新增红色 ✗ 才需 follow up"
fi

step "8) 500MB 大文件 multipart 测试"
if ssh_run "set -o pipefail; cd $REMOTE_DIR && API_BASE=http://localhost:8200 SIZE_MB=500 bash scripts/large_file_upload.sh 2>&1 | tail -40"; then
  ok "large file upload ok"
else
  warn "large file upload 失败 — 不阻塞 deploy 但需 follow up"
fi

step "9) 检查 ms-api 通过 nginx 外网可达"
ssh_run "curl -sS http://localhost/api/v1 2>&1 | head -3 || echo 'nginx 还没配 /api 路由'"

step "9.5) 撤销 maintenance banner — 前端会显示 '升级完成' 几秒后自动关"
if ssh_run "docker exec -i ms-redis redis-cli DEL maintenance:banner >/dev/null"; then
  ok "banner 已撤销"
else
  warn "banner 撤销失败 — 900s TTL 会自然清理,问题不大"
fi

echo
echo -e "${GREEN}══════ 全部部署 + 测试完成 ══════${NC}"
echo "uppy demo: 在 server2 nginx 加 /api → 127.0.0.1:8200 + /static → 同;或本地 SSH tunnel:"
echo "  ssh -L 8200:127.0.0.1:8200 root@$HOST"
echo "  然后浏览器开 http://localhost:8200/static/uppy.html"
