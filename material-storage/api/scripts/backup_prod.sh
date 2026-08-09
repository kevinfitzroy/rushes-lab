#!/usr/bin/env bash
# 生产备份脚本(issue #152 / ADR-0008 存储分层对齐):
#   - SSD 侧高频:PG 元数据 pg_dump(建议每日 cron)
#   - HDD 侧低频:原片 mc mirror 到本地异地挂载点(建议每周 cron;目标 = 第二块盘/外置存储)
# 在**生产服务器**上跑(需要 docker 访问);cron 示例与恢复演练见
# rushes-spec/material-storage/ops-manual.md「内网生产部署 · 备份 / 恢复」。
#
# 用法(服务器上,compose 项目目录或任意位置):
#   bash scripts/backup_prod.sh            # 默认只 pg_dump(高频日备)
#   bash scripts/backup_prod.sh --mirror   # 只跑原片 mirror(低频周备)
#   bash scripts/backup_prod.sh --all      # pg_dump + mirror 都跑
#
# 环境变量(均有默认):
#   COMPOSE_DIR        compose 项目根(默认 /root/material-storage-api;含 .env)
#   PG_BACKUP_DIR      pg_dump 落盘目录(默认 ${COMPOSE_DIR}/backups/pg;生产建议 SSD 挂载点)
#   PG_RETENTION_DAYS  pg_dump 保留天数(默认 7;find -mtime 清理)
#   MINIO_MIRROR_TARGET  mc mirror 目标(容器内路径;默认 /backup-mirror/ms-dev —
#                        host 侧由 poc/minio compose 的 MINIO_BACKUP_DIR bind 挂载,
#                        生产指外部盘/异地挂载点,如 /mnt/backup → 容器 /backup-mirror)
#   MINIO_MIRROR_BUCKET  原片 bucket(默认 ms-dev)
#   ⚠️ ADR-0008 分层后缩略图在独立实例(poc-minio-thumbs)的独立 bucket(ms-thumbs),
#      不在本备份路径内 —— 缩略图可从原片重生成,不算数据丢失,靠 backfill 重建
#      (见 ops-manual §10.4 / §10.5;切 ms-thumbs 后用 backfill_thumbnails --force)
set -euo pipefail

COMPOSE_DIR="${COMPOSE_DIR:-/root/material-storage-api}"
PG_BACKUP_DIR="${PG_BACKUP_DIR:-${COMPOSE_DIR}/backups/pg}"
PG_RETENTION_DAYS="${PG_RETENTION_DAYS:-7}"
MINIO_MIRROR_TARGET="${MINIO_MIRROR_TARGET:-/backup-mirror/ms-dev}"
MINIO_MIRROR_BUCKET="${MINIO_MIRROR_BUCKET:-ms-dev}"

MODE="${1:-pg}"
[[ "$MODE" == "--all" ]] && MODE="all"
[[ "$MODE" == "--mirror" ]] && MODE="mirror"
if [[ "$MODE" != "pg" && "$MODE" != "mirror" && "$MODE" != "all" ]]; then
  echo "usage: $0 [--all|--mirror]  (默认只 pg_dump)" >&2
  exit 1
fi

# MinIO 凭据(从 compose .env 读;脚本不打印值)
if [[ ! -f "$COMPOSE_DIR/.env" ]]; then
  echo "ERROR: $COMPOSE_DIR/.env 不存在" >&2
  exit 1
fi
MINIO_ACCESS_KEY=$(grep -E '^MINIO_ACCESS_KEY=' "$COMPOSE_DIR/.env" | head -1 | cut -d= -f2-)
MINIO_SECRET_KEY=$(grep -E '^MINIO_SECRET_KEY=' "$COMPOSE_DIR/.env" | head -1 | cut -d= -f2-)
[[ -n "$MINIO_ACCESS_KEY" && -n "$MINIO_SECRET_KEY" ]] || {
  echo "ERROR: .env 缺 MINIO_ACCESS_KEY / MINIO_SECRET_KEY" >&2; exit 1
}

# ─── pg_dump(SSD 侧,高频)─────────────────────────────────────────────────
if [[ "$MODE" == "pg" || "$MODE" == "all" ]]; then
  mkdir -p "$PG_BACKUP_DIR"
  TS=$(date +%Y%m%d-%H%M%S)
  OUT="$PG_BACKUP_DIR/material-storage-${TS}.sql.gz"
  echo "── pg_dump → $OUT"
  ( cd "$COMPOSE_DIR" && docker compose exec -T ms-db \
      pg_dump -U msuser -d material_storage --no-owner ) | gzip > "$OUT"
  SIZE=$(du -h "$OUT" | cut -f1)
  echo "✓ pg_dump done ($SIZE)"
  # 保留期清理
  find "$PG_BACKUP_DIR" -name 'material-storage-*.sql.gz' -mtime "+${PG_RETENTION_DAYS}" \
    -delete -print | sed 's/^/  清理(超期): /'
fi

# ─── mc mirror(HDD 原片 → 本地异地,低频)──────────────────────────────────
if [[ "$MODE" == "mirror" || "$MODE" == "all" ]]; then
  echo "── mc mirror: $MINIO_MIRROR_BUCKET → $MINIO_MIRROR_TARGET(容器内路径)"
  # 凭据走 env 注入(MC_HOST_<alias>),不进进程参数(host 上 ps 不可见)
  MC_URL=$(python3 -c 'import urllib.parse, sys
k, s = sys.argv[1], sys.argv[2]
print("http://%s:%s@127.0.0.1:9000" % (urllib.parse.quote(k, safe=""), urllib.parse.quote(s, safe="")))' \
    "$MINIO_ACCESS_KEY" "$MINIO_SECRET_KEY")
  docker exec -e "MC_HOST_backup-src=$MC_URL" poc-pigsty-minio mc mirror --overwrite \
    "backup-src/${MINIO_MIRROR_BUCKET}" "$MINIO_MIRROR_TARGET"
  echo "✓ mc mirror done(host 侧挂载点见 MINIO_BACKUP_DIR compose 变量)"
fi

echo "═══ 备份完成 ═══"
