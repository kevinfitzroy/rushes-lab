#!/usr/bin/env bash
# e2e_test.sh — Phase B-2 完整 endpoint 流程测试。
# 假设:
#   - dev_bootstrap.py 已跑过(2 user / org / project / folders / openfga tuples 都建好)
#   - ms-api 在 API_BASE 可达
#   - MinIO bucket ms-dev 已建
# 用法:
#   API_BASE=http://localhost:8200 bash scripts/e2e_test.sh
set -euo pipefail

API_BASE="${API_BASE:-http://localhost:8200}"
ADMIN="${ADMIN_USER_ID:-00000000-0000-0000-0000-000000000001}"
MEMBER="${MEMBER_USER_ID:-00000000-0000-0000-0000-000000000002}"
PROJECT="${PROJECT_ID:-00000000-0000-0000-0000-0000000000b1}"
NORMAL_F="${NORMAL_FOLDER_ID:-00000000-0000-0000-0000-0000000000c1}"
SENSITIVE_F="${SENSITIVE_FOLDER_ID:-00000000-0000-0000-0000-0000000000c2}"
BUCKET="${BUCKET:-ms-dev}"

GREEN='\033[0;32m'; RED='\033[0;31m'; YEL='\033[0;33m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $*"; }
fail() { echo -e "${RED}✗${NC} $*"; exit 1; }
step() { echo -e "\n${YEL}═══${NC} $* ${YEL}═══${NC}"; }

# 通用 helper:as <user_id> METHOD path [body]
as() {
  local uid=$1 method=$2 path=$3 body=${4:-}
  if [[ -n "$body" ]]; then
    curl -sS -X "$method" -H "X-User-Id: $uid" -H "Content-Type: application/json" \
         -d "$body" "${API_BASE}${path}" -w "\n__HTTP_%{http_code}__"
  else
    curl -sS -X "$method" -H "X-User-Id: $uid" "${API_BASE}${path}" -w "\n__HTTP_%{http_code}__"
  fi
}

assert_status() {
  local resp=$1 expected=$2 label=$3
  local code
  code=$(echo "$resp" | grep -oE '__HTTP_[0-9]+__' | tr -d 'HTP_' | tr -d '_')
  if [[ "$code" != "$expected" ]]; then
    echo "$resp"
    fail "$label expected HTTP $expected got $code"
  fi
  ok "$label (HTTP $code)"
}

extract_json() {
  echo "$1" | sed '/__HTTP_/d'
}

step "S0 健康检查 + cleanup 残留 invitations"
r=$(curl -sS "${API_BASE}/healthz")
echo "$r" | grep -q '"status":"ok"' && ok "/healthz ok" || fail "healthz failed: $r"
# 撤销 bob 的 sensitive_folder 邀请(both permanent + temporary;404 也 OK)
curl -sS -X DELETE -H "X-User-Id: $ADMIN" "${API_BASE}/api/v1/folders/$SENSITIVE_F/invite/user/$MEMBER?permanent=true" -o /dev/null
curl -sS -X DELETE -H "X-User-Id: $ADMIN" "${API_BASE}/api/v1/folders/$SENSITIVE_F/invite/user/$MEMBER?permanent=false" -o /dev/null
ok "cleanup done"

step "S1 admin (alice) 看 /auth/me"
r=$(as "$ADMIN" GET /api/v1/auth/me)
assert_status "$r" 200 "alice /me"
extract_json "$r"

step "S2 alice 列出 projects(应包含 dev-clinic 项目)"
r=$(as "$ADMIN" GET /api/v1/projects)
assert_status "$r" 200 "alice list projects"
echo "$(extract_json "$r")" | grep -q "$PROJECT" && ok "project found in list" || fail "project not in list"

step "S3 bob (member) 列出 projects"
r=$(as "$MEMBER" GET /api/v1/projects)
assert_status "$r" 200 "bob list projects"
echo "$(extract_json "$r")" | grep -q "$PROJECT" && ok "bob can see project (via editor relation)" || fail "bob can't see project"

step "S4 bob 列出 folders — 应该只看到 normal,看不到 sensitive(未邀请)"
r=$(as "$MEMBER" GET "/api/v1/folders?project_id=$PROJECT")
assert_status "$r" 200 "bob list folders"
json=$(extract_json "$r")
echo "$json" | grep -q "$NORMAL_F" && ok "bob sees normal folder" || fail "bob can't see normal folder"
echo "$json" | grep -q "$SENSITIVE_F" && fail "bob shouldn't see sensitive folder!" || ok "bob does NOT see sensitive folder ✓"

step "S5 alice 列出 folders — 应该都看见"
r=$(as "$ADMIN" GET "/api/v1/folders?project_id=$PROJECT")
assert_status "$r" 200 "alice list folders"
json=$(extract_json "$r")
echo "$json" | grep -q "$NORMAL_F" && echo "$json" | grep -q "$SENSITIVE_F" \
  && ok "alice sees both folders" || fail "alice missing folders"

step "S6 bob 试图列 sensitive folder 内 assets — 应 403"
r=$(as "$MEMBER" GET "/api/v1/assets?folder_id=$SENSITIVE_F")
assert_status "$r" 403 "bob list sensitive assets denied"

step "S7 bob 上传到普通 folder (小文件 1KB)"
upload_resp=$(as "$MEMBER" POST /api/v1/assets/uploads \
  "{\"folder_id\":\"$NORMAL_F\",\"filename\":\"hello.txt\",\"content_type\":\"text/plain\",\"size_bytes\":1024}")
assert_status "$upload_resp" 200 "bob create upload (normal)"
upload_json=$(extract_json "$upload_resp")
UPLOAD_ID=$(echo "$upload_json" | python3 -c 'import sys,json;print(json.load(sys.stdin)["upload_id"])')
KEY=$(echo "$upload_json" | python3 -c 'import sys,json;print(json.load(sys.stdin)["key"])')
ok "upload_id=$UPLOAD_ID key=$KEY"

# sign part 1
r=$(as "$MEMBER" GET "/api/v1/assets/uploads/$UPLOAD_ID/parts/1?bucket=$BUCKET&key=$(printf %s "$KEY" | python3 -c 'import sys,urllib.parse;print(urllib.parse.quote(sys.stdin.read()))')")
assert_status "$r" 200 "sign part 1"
PART_URL=$(extract_json "$r" | python3 -c 'import sys,json;print(json.load(sys.stdin)["url"])')

# PUT 1KB 数据
dd if=/dev/urandom of=/tmp/hello.bin bs=1024 count=1 2>/dev/null
HTTP=$(curl -sS -o /tmp/put.out -w "%{http_code}" -X PUT --data-binary @/tmp/hello.bin "$PART_URL")
[[ "$HTTP" == "200" ]] && ok "PUT part 1 OK" || fail "PUT part 1 HTTP=$HTTP"
ETAG=$(curl -sI "$PART_URL" 2>/dev/null | grep -i etag | tr -d '\r' || true)
# 重新 PUT 拿到 etag(curl -i)
ETAG=$(curl -sS -i -X PUT --data-binary @/tmp/hello.bin "$PART_URL" 2>/dev/null | awk 'BEGIN{IGNORECASE=1} /^etag:/{gsub(/\r/,"");gsub(/"/,"");sub(/^[^:]+: */,"");print;exit}')
ok "part 1 ETag=$ETAG"

# complete
r=$(as "$MEMBER" POST "/api/v1/assets/uploads/$UPLOAD_ID/complete" \
  "{\"upload_id\":\"$UPLOAD_ID\",\"bucket\":\"$BUCKET\",\"key\":\"$KEY\",\"parts\":[{\"PartNumber\":1,\"ETag\":\"$ETAG\"}]}")
assert_status "$r" 200 "complete upload"
ASSET_ID=$(extract_json "$r" | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')
ok "asset_id=$ASSET_ID"

step "S8 bob 列普通 folder assets"
r=$(as "$MEMBER" GET "/api/v1/assets?folder_id=$NORMAL_F")
assert_status "$r" 200 "bob list normal assets"
extract_json "$r" | grep -q "$ASSET_ID" && ok "asset in list" || fail "asset not in list"

step "S9 bob 拿下载链接"
r=$(as "$MEMBER" POST "/api/v1/assets/$ASSET_ID/download-link" "{}")
assert_status "$r" 200 "bob download-link"
DL_URL=$(extract_json "$r" | python3 -c 'import sys,json;print(json.load(sys.stdin)["url"])')
DOWN=$(curl -sS -o /tmp/down.bin -w "%{http_code}" "$DL_URL")
[[ "$DOWN" == "200" ]] && ok "actual download OK" || fail "download HTTP=$DOWN"
diff -q /tmp/hello.bin /tmp/down.bin && ok "downloaded content matches" || fail "content mismatch"

step "S10 bob 申请进入 sensitive folder(action=access,permanent)"
r=$(as "$MEMBER" POST /api/v1/approvals \
  "{\"target_type\":\"sensitive_folder\",\"target_id\":\"$SENSITIVE_F\",\"action\":\"access\",\"reason\":\"e2e test - sensitive access\"}")
assert_status "$r" 201 "bob submit approval (access)"
APPROVAL_ID=$(extract_json "$r" | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')
ok "approval_id=$APPROVAL_ID"

step "S11 bob 试图自批 — 应 403"
r=$(as "$MEMBER" POST "/api/v1/approvals/$APPROVAL_ID/approve" "{}")
assert_status "$r" 403 "bob self-approve denied"

step "S12 alice 批准 approval"
r=$(as "$ADMIN" POST "/api/v1/approvals/$APPROVAL_ID/approve" "{\"decision_note\":\"e2e OK\"}")
assert_status "$r" 200 "alice approves"
extract_json "$r" | grep -q '"status":"approved"' && ok "status=approved" || fail "not approved"

step "S13 bob 重新列 folders — 现在应能看到 sensitive"
r=$(as "$MEMBER" GET "/api/v1/folders?project_id=$PROJECT")
extract_json "$r" | grep -q "$SENSITIVE_F" && ok "bob NOW sees sensitive folder" \
  || fail "bob still doesn't see sensitive folder (approval grant failed?)"

step "S14a bob 试图上传到 sensitive folder — 应 403(invited 只可 view,不可 edit)"
r=$(as "$MEMBER" POST /api/v1/assets/uploads \
  "{\"folder_id\":\"$SENSITIVE_F\",\"filename\":\"vip-clip.dat\",\"content_type\":\"application/octet-stream\",\"size_bytes\":512}")
assert_status "$r" 403 "bob upload sensitive denied (model: invited 不 can_edit)"

step "S14b alice (admin) 上传到 sensitive folder"
r=$(as "$ADMIN" POST /api/v1/assets/uploads \
  "{\"folder_id\":\"$SENSITIVE_F\",\"filename\":\"vip-clip.dat\",\"content_type\":\"application/octet-stream\",\"size_bytes\":512}")
assert_status "$r" 200 "alice create upload (sensitive)"
UPLOAD2=$(extract_json "$r" | python3 -c 'import sys,json;print(json.load(sys.stdin)["upload_id"])')
KEY2=$(extract_json "$r" | python3 -c 'import sys,json;print(json.load(sys.stdin)["key"])')

# sign + put + complete sensitive (alice)
PART_URL2=$(as "$ADMIN" GET "/api/v1/assets/uploads/$UPLOAD2/parts/1?bucket=$BUCKET&key=$(printf %s "$KEY2" | python3 -c 'import sys,urllib.parse;print(urllib.parse.quote(sys.stdin.read()))')" \
  | sed '/__HTTP_/d' | python3 -c 'import sys,json;print(json.load(sys.stdin)["url"])')
dd if=/dev/urandom of=/tmp/vip.bin bs=512 count=1 2>/dev/null
ETAG2=$(curl -sS -i -X PUT --data-binary @/tmp/vip.bin "$PART_URL2" 2>/dev/null | awk 'BEGIN{IGNORECASE=1} /^etag:/{gsub(/\r/,"");gsub(/"/,"");sub(/^[^:]+: */,"");print;exit}')
r=$(as "$ADMIN" POST "/api/v1/assets/uploads/$UPLOAD2/complete" \
  "{\"upload_id\":\"$UPLOAD2\",\"bucket\":\"$BUCKET\",\"key\":\"$KEY2\",\"parts\":[{\"PartNumber\":1,\"ETag\":\"$ETAG2\"}]}")
assert_status "$r" 200 "alice complete sensitive upload"
SENSITIVE_ASSET_ID=$(extract_json "$r" | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')

step "S14c bob (invited, can_view) 下载 alice 上传的 sensitive asset"
r=$(as "$MEMBER" POST "/api/v1/assets/$SENSITIVE_ASSET_ID/download-link" "{}")
assert_status "$r" 200 "bob download sensitive asset (via invited can_view)"

step "S15 admin 直接邀请测试(/folders/{id}/invite)— 撤销 + 重新邀请验证"
# 撤销刚才 approval 给的 invited
r=$(as "$ADMIN" DELETE "/api/v1/folders/$SENSITIVE_F/invite/user/$MEMBER?permanent=true")
assert_status "$r" 204 "alice revoke bob invitation"

# 再次重新邀请 (临时 1h)
r=$(as "$ADMIN" POST "/api/v1/folders/$SENSITIVE_F/invite" \
  "{\"user_id\":\"$MEMBER\",\"duration_seconds\":3600}")
assert_status "$r" 204 "alice invite bob (temporary 1h)"

step "S16 bob 申请 download 单文件(action=download,1h)"
r=$(as "$MEMBER" POST /api/v1/approvals \
  "{\"target_type\":\"asset\",\"target_id\":\"$ASSET_ID\",\"action\":\"download\",\"duration_seconds\":3600,\"reason\":\"e2e file-level download\"}")
assert_status "$r" 201 "file-level approval submit"
A2=$(extract_json "$r" | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')
r=$(as "$ADMIN" POST "/api/v1/approvals/$A2/approve" "{}")
assert_status "$r" 200 "alice approves file-level"

echo
echo -e "${GREEN}══════ ALL E2E TESTS PASSED ══════${NC}"
