#!/usr/bin/env bash
# 大文件 multipart 上传测试 — 500MB,分 16MB part。
# 用法:API_BASE=http://localhost:8200 bash scripts/large_file_upload.sh
set -euo pipefail

API_BASE="${API_BASE:-http://localhost:8200}"
MEMBER="${MEMBER_USER_ID:-00000000-0000-0000-0000-00000000u002}"
NORMAL_F="${NORMAL_FOLDER_ID:-00000000-0000-0000-0000-00000000f001}"
BUCKET="${BUCKET:-ms-dev}"
SIZE_MB="${SIZE_MB:-500}"
PART_MB=16
FILE=/tmp/large-${SIZE_MB}MB.bin

GREEN='\033[0;32m'; RED='\033[0;31m'; YEL='\033[0;33m'; NC='\033[0m'
step() { echo -e "\n${YEL}═══${NC} $* ${YEL}═══${NC}"; }
ok() { echo -e "${GREEN}✓${NC} $*"; }
fail() { echo -e "${RED}✗${NC} $*"; exit 1; }

step "生成 ${SIZE_MB}MB 测试文件 $FILE"
[[ -f "$FILE" ]] || dd if=/dev/urandom of="$FILE" bs=1M count="$SIZE_MB" 2>&1 | tail -1
ls -lh "$FILE"

step "create_multipart_upload"
RESP=$(curl -sS -X POST -H "X-User-Id: $MEMBER" -H "Content-Type: application/json" \
  -d "{\"folder_id\":\"$NORMAL_F\",\"filename\":\"large-${SIZE_MB}MB.bin\",\"content_type\":\"application/octet-stream\",\"size_bytes\":$((SIZE_MB * 1024 * 1024))}" \
  "${API_BASE}/api/v1/assets/uploads")
UPLOAD_ID=$(echo "$RESP" | python3 -c 'import sys,json;print(json.load(sys.stdin)["upload_id"])')
KEY=$(echo "$RESP" | python3 -c 'import sys,json;print(json.load(sys.stdin)["key"])')
ok "upload_id=$UPLOAD_ID key=$KEY"

step "分 ${PART_MB}MB part 上传"
NUM_PARTS=$(( (SIZE_MB + PART_MB - 1) / PART_MB ))
ok "总 ${NUM_PARTS} parts"

PARTS_JSON="["
TOTAL_START=$SECONDS
for ((i=1; i<=NUM_PARTS; i++)); do
  PART_START=$SECONDS

  # 拿 presigned PUT
  KEY_ENC=$(printf %s "$KEY" | python3 -c 'import sys,urllib.parse;print(urllib.parse.quote(sys.stdin.read()))')
  PART_URL=$(curl -sS -H "X-User-Id: $MEMBER" \
    "${API_BASE}/api/v1/assets/uploads/$UPLOAD_ID/parts/$i?bucket=$BUCKET&key=$KEY_ENC" \
    | python3 -c 'import sys,json;print(json.load(sys.stdin)["url"])')

  # 切 part 数据
  OFFSET_MB=$(( (i - 1) * PART_MB ))
  COUNT_MB=$PART_MB
  if (( i == NUM_PARTS )); then
    COUNT_MB=$(( SIZE_MB - OFFSET_MB ))
  fi
  PART_FILE=/tmp/part-$i.bin
  dd if="$FILE" of="$PART_FILE" bs=1M skip="$OFFSET_MB" count="$COUNT_MB" 2>/dev/null

  # PUT
  ETAG=$(curl -sS -i -X PUT --data-binary @"$PART_FILE" "$PART_URL" 2>/dev/null \
    | grep -i '^etag:' | head -1 | sed 's/^[Ee]tag: //; s/\r$//; s/"//g')
  [[ -n "$ETAG" ]] || fail "part $i upload failed (no ETag)"
  rm -f "$PART_FILE"

  PART_TIME=$((SECONDS - PART_START))
  echo "  part $i/$NUM_PARTS  ${COUNT_MB}MB  ETag=${ETAG:0:16}...  ${PART_TIME}s"
  if (( i > 1 )); then PARTS_JSON+=","; fi
  PARTS_JSON+="{\"PartNumber\":$i,\"ETag\":\"$ETAG\"}"
done
PARTS_JSON+="]"
TOTAL_TIME=$((SECONDS - TOTAL_START))
ok "全部 part 上传完毕,耗时 ${TOTAL_TIME}s ($(( SIZE_MB / (TOTAL_TIME > 0 ? TOTAL_TIME : 1) ))MB/s)"

step "complete_multipart_upload"
RESP=$(curl -sS -X POST -H "X-User-Id: $MEMBER" -H "Content-Type: application/json" \
  -d "{\"upload_id\":\"$UPLOAD_ID\",\"bucket\":\"$BUCKET\",\"key\":\"$KEY\",\"parts\":$PARTS_JSON}" \
  "${API_BASE}/api/v1/assets/uploads/$UPLOAD_ID/complete")
ASSET_ID=$(echo "$RESP" | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')
ok "ASSET_ID=$ASSET_ID"

step "校验下载"
DL_URL=$(curl -sS -X POST -H "X-User-Id: $MEMBER" -H "Content-Type: application/json" -d '{}' \
  "${API_BASE}/api/v1/assets/$ASSET_ID/download-link" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["url"])')
DOWN_START=$SECONDS
curl -sS -o /tmp/large-down.bin "$DL_URL"
DOWN_TIME=$((SECONDS - DOWN_START))
DOWN_SIZE=$(stat -c %s /tmp/large-down.bin 2>/dev/null || stat -f %z /tmp/large-down.bin)
ok "下载 ${DOWN_SIZE} bytes  ${DOWN_TIME}s"

# md5 校验
MD5_SRC=$(md5sum "$FILE" | awk '{print $1}')
MD5_DST=$(md5sum /tmp/large-down.bin | awk '{print $1}')
[[ "$MD5_SRC" == "$MD5_DST" ]] && ok "MD5 match: $MD5_SRC" || fail "MD5 MISMATCH src=$MD5_SRC dst=$MD5_DST"

rm -f /tmp/large-down.bin
echo -e "\n${GREEN}══════ 大文件上传 e2e 通过 ${SIZE_MB}MB ══════${NC}"
