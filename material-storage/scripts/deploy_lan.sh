#!/usr/bin/env bash
# 内网机(hh2)部署 —— 同步代码 + 落一份可查的版本记录。
#
# 用法(在 rushes-lab/material-storage 目录下跑):
#   bash scripts/deploy_lan.sh dev            # 同步到 dev 环境
#   bash scripts/deploy_lan.sh prod           # 同步到 prod 环境
#   bash scripts/deploy_lan.sh dev --restart  # 同步后顺带重启 api/worker
#
# 为什么要这个脚本:同一台机器上 dev 与 prod 并存,光看服务跑着分不清各自
# 停在哪个版本。每次同步都会重写目标机的 DEPLOYED.md,记下 git commit /
# 分支 / 时间 / 本机是否有未提交改动 —— 排查"线上到底是哪版代码"时先看它。
#
# 不覆盖目标机的 .env 与 docker-compose.override.yml(环境差异全在这两个文件里)。
set -euo pipefail

ENVNAME="${1:-}"
RESTART="${2:-}"
case "$ENVNAME" in
  dev)  SSH_USER=msdev;   REMOTE_DIR=/home/msdev/ms;   ENTRY="http://192.168.110.221:8090" ;;
  prod) SSH_USER=huanhua; REMOTE_DIR=/home/huanhua/ms; ENTRY="http://192.168.110.221" ;;
  *) echo "用法: bash scripts/deploy_lan.sh <dev|prod> [--restart]" >&2; exit 2 ;;
esac

HOST=hh2
[[ -d api && -d poc ]] || { echo "请在 material-storage/ 目录下执行" >&2; exit 2; }

GIT_COMMIT=$(git rev-parse --short HEAD)
GIT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
GIT_SUBJECT=$(git log -1 --format=%s)
GIT_DATE=$(git log -1 --format=%cd --date=format:'%Y-%m-%d %H:%M')
# 注意 || true:工作区干净时 grep 无匹配返回 1,配合 set -e + pipefail 会直接退出
DIRTY=$( { git status --porcelain -- . | grep -v '^?? ' || true; } | wc -l | tr -d ' ')
DEPLOY_AT=$(date '+%Y-%m-%d %H:%M:%S %Z')
DEPLOY_BY="${USER:-unknown}@$(hostname -s)"

echo "═══ 同步 $ENVNAME ($GIT_COMMIT on $GIT_BRANCH) ═══"
[[ "$DIRTY" != "0" ]] && echo "⚠️  本机有 $DIRTY 个未提交改动,部署的不完全等于 $GIT_COMMIT"

# --inplace:nginx conf 等是 bind mount,换 inode 会让容器内看到 stale 文件
rsync -a --inplace \
  --exclude '.git' --exclude '.env' --exclude 'node_modules' --exclude 'uv.lock' \
  --exclude '__pycache__' --exclude '*.pyc' --exclude '.venv' --exclude 'static/web' \
  --exclude 'data' --exclude 'data-dev' --exclude 'data-thumbs' --exclude 'backup-mirror' \
  --exclude 'docker-compose.override.yml' \
  ./ "$HOST:/tmp/ms-sync-$ENVNAME/"

ssh "$HOST" "sudo rsync -a --inplace \
    --exclude .env --exclude docker-compose.override.yml --exclude 'static/web' \
    /tmp/ms-sync-$ENVNAME/ $REMOTE_DIR/ && \
  sudo chown -R $SSH_USER:$SSH_USER $REMOTE_DIR && \
  sudo rm -rf /tmp/ms-sync-$ENVNAME"

# ─── 版本记录:目标机上唯一的"当前跑的是哪一版"事实源 ───
ssh "$HOST" "sudo -u $SSH_USER tee $REMOTE_DIR/DEPLOYED.md >/dev/null" <<EOF
# 部署版本 — $ENVNAME

> 本文件由 \`scripts/deploy_lan.sh\` 自动生成,**不要手改**。
> 查看:\`ssh hh2 'cat $REMOTE_DIR/DEPLOYED.md'\`

| | |
| --- | --- |
| 环境 | **$ENVNAME** |
| 业务入口 | $ENTRY |
| 系统用户 | \`$SSH_USER\` |
| 代码目录 | \`$REMOTE_DIR\` |
| **git commit** | **\`$GIT_COMMIT\`** |
| 分支 | \`$GIT_BRANCH\` |
| commit 信息 | $GIT_SUBJECT |
| commit 时间 | $GIT_DATE |
| 部署时间 | $DEPLOY_AT |
| 部署者 | $DEPLOY_BY |
| 源端未提交改动 | $DIRTY 个$([[ "$DIRTY" != "0" ]] && echo " ⚠️ 实际内容与该 commit 有出入" || echo "") |

## 不随本脚本同步的东西

\`.env\` 与 \`docker-compose.override.yml\` —— 两套环境的差异(端口、卷路径、
compose project 名、容器名后缀)全在这两个文件里,同步时始终跳过。

## 校验当前运行的代码是否等于本记录

\`\`\`bash
# 容器里的 app/ 是 bind mount,直接比对文件即可
ssh hh2 'sudo diff -r $REMOTE_DIR/api/app \\
  <(sudo docker exec \$(cd $REMOTE_DIR/api && sudo docker compose ps -q ms-api) tar -cf - -C /app app | tar -xf - -O) 2>&1 | head'
\`\`\`
EOF

echo "✓ 代码已同步,版本记录已写入 $REMOTE_DIR/DEPLOYED.md"

if [[ "$RESTART" == "--restart" ]]; then
  echo "═══ 重启 api / worker ═══"
  if [[ "$ENVNAME" == "dev" ]]; then
    ssh "$HOST" "sudo -u msdev bash -c 'cd $REMOTE_DIR/api && docker compose restart ms-api ms-worker'"
  else
    ssh "$HOST" "cd $REMOTE_DIR/api && sudo docker compose restart ms-api ms-worker"
  fi
  echo "✓ 已重启"
fi

echo
ssh "$HOST" "cat $REMOTE_DIR/DEPLOYED.md" | sed -n '5,20p'
