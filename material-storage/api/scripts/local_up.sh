#!/usr/bin/env bash
# local_up.sh — material-storage 本地一键 docker 部署(local-dev-runbook §8.1 的落地)
#
# 一条命令完成:
#   1. 起依赖栈 ../poc/minio(MinIO + OpenFGA;compose project 固定 poc-pigsty-minio,
#      生成 api compose 硬编码引用的外部网络 poc-pigsty-minio_poc-net)
#   2. OpenFGA store + 权限 model(已有合法 store 则复用)
#   3. api/.env 不存在则从 .env.example 生成(容器名 host + 本地端口 + 随机 JWT secret)
#   4. build + 起 ms-db / ms-redis / ms-api / ms-worker
#   5. alembic upgrade head + seed_demo_data + dev_bootstrap(均幂等)
#
# 用法:
#   bash scripts/local_up.sh               # 全量(幂等,重复跑安全)
#   bash scripts/local_up.sh --web         # 收尾后前台起 vite dev server(Ctrl+C 只停前端)
#   bash scripts/local_up.sh --refresh-model  # 强制重推 OpenFGA model(store 数据保留)
#
# 环境:
#   - Git Bash(Windows)与 Linux 均可跑;需 docker compose v2 + curl + openssl
#   - 镜像源口径(有意与 Dockerfile/compose 默认不同):Dockerfile/compose 默认清华源,
#     本脚本默认阿里云 —— 本机网络对清华源包文件 403,不换源 build 必失败。
#     可用环境变量覆盖回清华或其它:
#       APT_MIRROR=mirrors.tuna.tsinghua.edu.cn PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple bash scripts/local_up.sh
#   - 跑集成测试前先清登录限流:docker compose exec -T ms-redis redis-cli FLUSHALL
set -euo pipefail

MS_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"   # material-storage/
API_DIR="$MS_ROOT/api"
POC_DIR="$MS_ROOT/poc/minio"
WEB_DIR="$MS_ROOT/web"
POC_PROJECT="poc-pigsty-minio"                   # api compose 的外部网络名依赖它
OPENFGA_URL="http://localhost:8089"
API_URL="http://localhost:8200"

APT_MIRROR="${APT_MIRROR:-mirrors.aliyun.com}"
PIP_INDEX_URL="${PIP_INDEX_URL:-https://mirrors.aliyun.com/pypi/simple}"

REFRESH_MODEL=0
WITH_WEB=0
TMP_DIR=""
trap '[ -n "$TMP_DIR" ] && rm -rf "$TMP_DIR" || true' EXIT
for arg in "$@"; do
  case "$arg" in
    --refresh-model) REFRESH_MODEL=1 ;;
    --web) WITH_WEB=1 ;;
    *) echo "unknown arg: $arg (支持 --web / --refresh-model)"; exit 2 ;;
  esac
done

GREEN='\033[0;32m'; YEL='\033[0;33m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $*"; }
step() { echo -e "\n${YEL}═══ $* ═══${NC}"; }
die()  { echo "ERROR: $*" >&2; exit 1; }

dc() { docker compose -f "$API_DIR/docker-compose.yml" "$@"; }

# 注:不要全局 export MSYS_NO_PATHCONV —— 那会连 compose 文件路径一起禁转译。
# 只有带容器内路径的 docker run(-v …:/work)需要它,在那条命令上局部生效。

# ─── 0) preflight ─────────────────────────────────────────────────────
step "0/6 preflight"
docker info >/dev/null 2>&1 || die "docker daemon 没起来(Windows: 启动 Docker Desktop)"
docker compose version >/dev/null 2>&1 || die "需要 docker compose v2"
command -v curl >/dev/null || die "缺 curl"
command -v openssl >/dev/null || die "缺 openssl"
ok "docker / compose / curl / openssl 就绪"

# ─── 1) 依赖栈(MinIO + OpenFGA)──────────────────────────────────────
step "1/6 起依赖栈 poc/minio(project=$POC_PROJECT)"
docker compose -p "$POC_PROJECT" -f "$POC_DIR/docker-compose.yml" up -d \
  pigsty-minio poc-minio-thumbs poc-openfga-db poc-openfga-migrate poc-openfga

for i in $(seq 1 30); do
  curl -sf "$OPENFGA_URL/healthz" 2>/dev/null | grep -q SERVING && break
  [ "$i" = 30 ] && die "OpenFGA 60s 内没就绪,看日志:docker logs poc-openfga"
  sleep 2
done
ok "OpenFGA SERVING"

# ─── 2) api/.env(不存在才生成,已有则复用)────────────────────────────
step "2/6 api/.env"
if [ ! -f "$API_DIR/.env" ]; then
  sed -e 's|@localhost:5432|@ms-db:5432|' \
      -e 's|redis://localhost:6379|redis://ms-redis:6379|' \
      -e 's|^MINIO_ENDPOINT_PUBLIC=.*|MINIO_ENDPOINT_PUBLIC=http://localhost:6100|' \
      -e 's|^MINIO_ACCESS_KEY=.*|MINIO_ACCESS_KEY=minioadmin|' \
      -e 's|^MINIO_SECRET_KEY=.*|MINIO_SECRET_KEY=minioadmin-poc-2026|' \
      -e 's|^MINIO_DEFAULT_BUCKET=.*|MINIO_DEFAULT_BUCKET=ms-dev|' \
      -e 's|^# SESSION_COOKIE_SECURE=.*|SESSION_COOKIE_SECURE=false|' \
      -e "s|^SESSION_JWT_SECRET=.*|SESSION_JWT_SECRET=$(openssl rand -hex 32)|" \
      "$API_DIR/.env.example" > "$API_DIR/.env"
  ok "已从 .env.example 生成 .env(容器名 host / http cookie / 随机 secret)"
else
  ok ".env 已存在,复用(不覆盖)"
fi

# ─── 3) OpenFGA store + model ─────────────────────────────────────────
step "3/6 OpenFGA store + model"
STORE_ID="$(grep -E '^OPENFGA_STORE_ID=' "$API_DIR/.env" | head -1 | cut -d= -f2-)"
if [ -n "$STORE_ID" ] && curl -sf "$OPENFGA_URL/stores/$STORE_ID" >/dev/null 2>&1; then
  ok "复用已有 store $STORE_ID"
else
  RESP="$(curl -sf -X POST "$OPENFGA_URL/stores" -H 'content-type: application/json' \
            -d '{"name":"material-storage-dev"}')" || die "建 store 失败"
  STORE_ID="$(echo "$RESP" | sed -n 's/.*"id":"\([^"]*\)".*/\1/p')"
  [ -n "$STORE_ID" ] || die "store 响应里没解析到 id: $RESP"
  sed -i.bak "s|^OPENFGA_STORE_ID=.*|OPENFGA_STORE_ID=$STORE_ID|" "$API_DIR/.env" && rm -f "$API_DIR/.env.bak"
  ok "新建 store $STORE_ID(已写回 .env)"
fi

HAS_MODEL=0
curl -s "$OPENFGA_URL/stores/$STORE_ID/authorization-models" | grep -q '"id"' && HAS_MODEL=1
if [ "$HAS_MODEL" = 1 ] && [ "$REFRESH_MODEL" = 0 ]; then
  ok "store 已有 model,跳过(重推:--refresh-model)"
else
  TMP_DIR="$(mktemp -d)"
  # 从 store.fga.yaml 抽 model: 块(遇非缩进行即停),去掉 2 空格缩进
  awk '/^model: \|/{f=1;next} f && /^[^ ]/{exit} f' "$MS_ROOT/poc/openfga/store.fga.yaml" \
    | sed 's/^  //' > "$TMP_DIR/model.fga"
  [ -s "$TMP_DIR/model.fga" ] || die "store.fga.yaml 里没抽到 model"

  # fga DSL → JSON(官方 CLI 镜像,免装二进制)
  # HOST_DIR 用 Windows 形式(pwd -W),配合 MSYS_NO_PATHCONV=1(仅本条命令,
  # 防止 Git Bash 把容器内路径 /work 转译成宿主机路径);Linux 下两者均无副作用
  HOST_DIR="$(cd "$TMP_DIR" && pwd -W 2>/dev/null || pwd)"
  MSYS_NO_PATHCONV=1 docker run --rm -v "$HOST_DIR:/work:ro" openfga/cli:latest \
    model transform --input-format fga --file /work/model.fga > "$TMP_DIR/model.json" \
    || die "fga model transform 失败"
  RESP="$(curl -sf -X POST "$OPENFGA_URL/stores/$STORE_ID/authorization-models" \
            -H 'content-type: application/json' --data-binary @"$TMP_DIR/model.json")" \
    || die "model 推送失败: $RESP"
  ok "model 已推送: $(echo "$RESP" | sed -n 's/.*"authorization_model_id":"\([^"]*\)".*/\1/p')"
fi

# ─── 4) api 栈 build + up ─────────────────────────────────────────────
step "4/6 build + 起 api 栈(apt=$APT_MIRROR)"
export APT_MIRROR PIP_INDEX_URL
dc up -d --build
for i in $(seq 1 30); do
  curl -sf "$API_URL/healthz" >/dev/null 2>&1 && break
  [ "$i" = 30 ] && die "ms-api 60s 内没就绪,看日志:docker compose -f $API_DIR/docker-compose.yml logs ms-api"
  sleep 2
done
ok "ms-api healthz OK"

# ─── 5) migrate + seed + dev 密码(幂等)─────────────────────────────
step "5/6 alembic + seed + dev 密码"
dc exec -T ms-api alembic upgrade head
dc exec -T ms-api python -m scripts.seed_demo_data 2>&1 | tail -1
dc exec -T ms-api python -m scripts.dev_bootstrap 2>&1 | tail -1
# seed 账号设固定 dev 密码 → 浏览器走 /login 账号密码登录测角色(与生产同链路,
# 不再依赖 X-User-Id dev 通道;alice/bob 首次用 email 匹配,之后 username 已设。
# 注意:exec 会吃掉循环 stdin,必须 </dev/null,否则 heredoc 剩余行被吞)
while read -r ident user pw; do
  dc exec -T ms-api python -m scripts.set_password "$ident" --username "$user" --password "$pw" </dev/null >/dev/null \
    || die "set_password $ident 失败"
done <<EOF
alice@dev.local alice alice2026
bob@dev.local bob bobdev2026
evan@dev.local evan evan2026
Outsider outsider outsider2026
EOF
ok "迁移 + 双 seed + dev 密码完成"

# ─── 6) 汇总 ──────────────────────────────────────────────────────────
step "6/6 就绪"
cat <<EOF
  前端(先起):  cd material-storage/web && pnpm dev
  密码登录:     http://localhost:5173/ms-static/web/login(与生产同链路)
                  alice     / alice2026     org admin + 系统 admin
                  bob       / bob2026       项目 member(无敏感目录权限)
                  evan      / evan2026      demo org admin(seed 契约账号)
                  outsider  / outsider2026  无权限账号(负向测试)
  API:          $API_URL/healthz
  MinIO Console: http://localhost:6101(minioadmin / minioadmin-poc-2026)
  OpenFGA:       http://localhost:3001/playground · store $STORE_ID
  dev 通道:      /ms-static/web/dev-login(X-User-Id,冒烟任意 UUID 用)
  集成测试:      docker cp tests ms-api:/app/tests && \\
                docker compose -f $API_DIR/docker-compose.yml exec -T ms-api python -m pytest tests/ -v
                (容器需先装 dev 依赖:… exec -T ms-api pip install pytest pytest-asyncio freezegun aiosqlite;
                 跑前清登录限流:… exec -T ms-redis redis-cli FLUSHALL)
EOF

if [ "$WITH_WEB" = 1 ]; then
  step "--web:前台起 vite dev server(Ctrl+C 退出,容器不受影响)"
  [ -n "${TMP_DIR:-}" ] && rm -rf "$TMP_DIR"; trap - EXIT
  cd "$WEB_DIR" && pnpm dev
fi
