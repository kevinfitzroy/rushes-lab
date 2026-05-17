# nc/ — Nextcloud PoC 路线

> ⚠️ **历史**(2026-05-17)。Nextcloud 路线在 ADR-0003 时已 drop;后续 [ADR-0005](../../../rushes-spec/material-storage/decisions/0005-drop-seafile-middle-layer-minio-only.md) 进一步抛弃所有第三方文件管理底座,改走自研 + MinIO。本目录仅作历史参考。

落地 v0.3 §8 部署最小配置。覆盖 issue #12 验收用的部署骨架(性能压测脚本另立)。

## 启动

```bash
# 1. 准备 env(在 ../poc/ 根目录)
cp ../.env.example ../.env
vim ../.env   # 填 NC_DB_PASSWORD / NC_ADMIN_PASSWORD / NC_HOST / NC_DATA_DIR

# 2. 拉镜像 + 起容器
docker compose up -d

# 3. 等 init(首次拉镜像 + NC bootstrap ~ 2 分钟)
docker compose logs -f nc-app   # 观察 "apache2 -DFOREGROUND" 出现

# 4. 浏览器进
open http://<NC_HOST>:${NC_PORT:-8081}
# 用 NC_ADMIN_USER / NC_ADMIN_PASSWORD 登录

# 5. (可选)装 FFmpeg 让视频缩略图能跑
docker exec -u root nc-app apt-get update && \
  docker exec -u root nc-app apt-get install -y ffmpeg
```

## 灌数据集

数据集生成见 `../dataset-gen/`。NC datadirectory 在 `${NC_DATA_DIR}`(默认 `/srv/poc-data/nc-data`),NC 期望的结构:

```
${NC_DATA_DIR}/
├── <admin>/
│   └── files/
│       ├── <数据集目录 1>/
│       ├── <数据集目录 2>/
```

`<admin>` 是 NEXTCLOUD_ADMIN_USER。NC bootstrap 后会自动建该目录。把 dataset-gen 输出的整个 user_xxx 目录拷/移到这里,然后:

```bash
docker exec -u www-data nc-app php occ files:scan --all
```

让 NC 索引这些文件到 `oc_filecache`。

> **重要:** v0.3 §3.4 inotify 路径过滤约束 — 任何外部进程在 `${NC_DATA_DIR}/` 旁路读取时,**必须忽略** `appdata_<instanceid>/`、`<user>/files_trashbin/`、`<user>/files_versions/`,否则 NC 自己的写入会持续触发外部观察。

## 关停 / 重置

```bash
docker compose down                  # 容器关停,volumes 保留
docker compose down -v               # 同时删 PG volume(下次重启重新 bootstrap)
rm -rf ${NC_DATA_DIR}                # 删 datadirectory(慎,丢用户文件)
```

## 性能验收测试(issue #12)

部署起来后,跑 `../tests/` 下脚本(待写齐):

- 目录浏览 P50/P95(用 cURL + WebDAV PROPFIND)
- `occ files:scan` 全扫耗时
- `occ preview:generate-all` 耗时(撞墙第一位,expert E)
- `oc_filecache` 增长 + `pg_repack` 收敛
- 30+ 用户并发桌面同步冲突率(需要桌面客户端真机或模拟)

记得**回写结果到** v0.3 §6.4 PoC 实测结果记录(待建)。

## 资源建议

| 数据集 | 推荐 RAM | 推荐 CPU | 磁盘 |
| --- | --- | --- | --- |
| 1k 文件(Stage 1 sanity) | 4 GB | 2 核 | 10 GB |
| 50w 文件 | **16 GB** | **8 核** | 500 GB(sparse)/ 多 TB(realistic)|
| 100w 文件 | 16-32 GB | 8 核 | 1+ TB |

PoC 机器内存 < 16 GB 时,把 docker-compose.yml 里 Postgres `shared_buffers` 等参数按比例下调。

## 已知问题

- 默认镜像 `nextcloud:30-apache` 未装 ffmpeg,视频预览跑不动 → 容器内 apt install,或换 nextcloud:30-fpm-alpine + 自建 Dockerfile
- nc-cron 容器与 nc-app 共享 datadirectory,若同时写入大量文件,内部 cron 也会读盘 — 不影响测试结果,但 IO 监控时记得排除
- 这个 compose **没有 OIDC 配置** — Stage 1 PoC 用 NC 内置账号即可;接飞书 OIDC 是 issue #14 的事,届时装 NC 的 `user_oidc` app + 配 bridge endpoints
