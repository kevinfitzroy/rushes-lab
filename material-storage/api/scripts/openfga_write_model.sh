#!/usr/bin/env bash
# OpenFGA model update — push store.fga.yaml 内 model: 段 to server2 OpenFGA store (#129)。
#
# 流程:
#   1. 本机 python 从 store.fga.yaml 抽 model 字段(纯 .fga DSL)
#   2. scp DSL 到 server2 /tmp/model.fga
#   3. server2 上 docker run openfga/cli model transform --input-format fga → JSON
#   4. curl POST /stores/{id}/authorization-models 产新 model_id
#   5. .env 不固定 OPENFGA_MODEL_ID → 重启 ms-api 自动用 latest
#
# 跑法(从本机 cd material-storage/api):
#   bash scripts/openfga_write_model.sh
set -euo pipefail

HOST="${HOST:-8.156.34.238}"
SSH_USER="${SSH_USER:-root}"
SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=10"

YAML_LOCAL="${1:-../poc/openfga/store.fga.yaml}"
[[ -f "$YAML_LOCAL" ]] || { echo "ERROR: yaml not found at $YAML_LOCAL"; exit 1; }

GREEN='\033[0;32m'; YEL='\033[0;33m'; NC='\033[0m'
ok() { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YEL}⚠${NC} $*"; }

echo "═══ 1) 本机抽 model 字段(纯 .fga DSL)═══"
DSL=$(python3 -c "
import yaml
d = yaml.safe_load(open('$YAML_LOCAL').read())
print(d['model'])
")
[[ -n "$DSL" ]] || { warn "model field empty"; exit 1; }
ok "DSL bytes=$(echo -n "$DSL" | wc -c | tr -d ' ')"

echo "═══ 2) scp DSL → server2:/tmp/model.fga ═══"
echo "$DSL" | ssh $SSH_OPTS "$SSH_USER@$HOST" "cat > /tmp/model.fga"
ok "DSL synced"

echo "═══ 3) docker run openfga/cli transform fga → JSON ═══"
MODEL_JSON=$(ssh $SSH_OPTS "$SSH_USER@$HOST" \
  "docker run --rm -v /tmp/model.fga:/data/model.fga openfga/cli:latest model transform --input-format fga --file /data/model.fga 2>&1")
if ! echo "$MODEL_JSON" | python3 -c 'import sys,json;json.load(sys.stdin)' 2>/dev/null; then
  warn "fga cli transform failed; head: ${MODEL_JSON:0:500}"
  exit 2
fi
ok "transformed: $(echo "$MODEL_JSON" | wc -c | tr -d ' ') bytes JSON"

echo "═══ 4) 获取 STORE_ID + POST model ═══"
STORE_ID=$(ssh $SSH_OPTS "$SSH_USER@$HOST" \
  "curl -s http://127.0.0.1:8089/stores | python3 -c 'import sys,json;print(json.load(sys.stdin)[\"stores\"][0][\"id\"])'")
echo "STORE_ID=$STORE_ID"

# 直接走 stdin 喂 curl,避开 shell quoting 噩梦
NEW_MODEL=$(echo "$MODEL_JSON" | ssh $SSH_OPTS "$SSH_USER@$HOST" \
  "curl -sS -X POST -H 'Content-Type: application/json' --data-binary @- http://127.0.0.1:8089/stores/$STORE_ID/authorization-models")

NEW_ID=$(echo "$NEW_MODEL" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d.get("authorization_model_id",""))' 2>/dev/null)
if [[ -z "$NEW_ID" ]]; then
  warn "model write failed; response: $NEW_MODEL"
  exit 3
fi
ok "OpenFGA model written: $NEW_ID"

echo ""
echo "── 提醒 ──"
echo "  .env 未固定 OPENFGA_MODEL_ID → 重启 ms-api 自动用 latest:"
echo "    ssh root@$HOST 'docker restart ms-api ms-worker'"
echo "  若 .env 设了固定 OPENFGA_MODEL_ID,需要 sed 替换为 $NEW_ID 再 force-recreate"
