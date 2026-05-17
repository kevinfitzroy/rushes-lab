# seafile/ — Seafile Pro + 本地 MinIO PoC(v0.5 收敛唯一路线)

> ⚠️ **历史**(2026-05-17)。Seafile 路线已被 [ADR-0005](../../../rushes-spec/material-storage/decisions/0005-drop-seafile-middle-layer-minio-only.md) supersede — 当前走自研 + MinIO 直存,不引入 Seafile 中间层。本目录仅作历史参考。

落地 [v0.5 §3.2](../../../rushes-spec/material-storage/research/file-management-system.md) Seafile Pro + 本地 MinIO 作 S3 backend 分层 + [ADR-0003](../../../rushes-spec/material-storage/decisions/0003-seafile-only-poc.md) 决策。覆盖 [Issue #23](https://github.com/kevinfitzroy/rushes-lab/issues/23) PoC-Seafile 部署骨架(性能压测脚本另立,见 `../tests/`)。

## ⚠️ 关键前提与 2026-05-15 实测 finding

详 [v0.5 §6.3](../../../rushes-spec/material-storage/research/file-management-system.md) F-X + F-1~F-6 + [ADR-0003 §"配套实施 finding"](../../../rushes-spec/material-storage/decisions/0003-seafile-only-poc.md)。摘要:

| # | 关键事实 | 影响 / 处理 |
| --- | --- | --- |
| **F-X** | Seafile CE 11.0.13 实测**无 S3 backend code path**(`strings seaf-server` 无 s3/aws/amazon 关键字);写 `[block_backend] name = s3` 后上传文件,blocks 仍写 local fs | **本路线必须 Seafile Pro Edition**,license 申请中(2026-05-16+) |
| F-1 | MySQL 8 默认 `caching_sha2_password` 与 seaf-server libmariadb 不兼容 | docker-compose 已用 **MariaDB 10.11 LTS** |
| F-2 | `seafileltd/seafile-mc:13.0` tag 不存在;latest = 11.0.13 | 占位 `:latest`(CE),拿到 Pro 后换 `seafileltd/seafile-pro-mc:<ver>` |
| F-3 | `seahub_settings.override.py` 不被 import | 文件已重命名 `local_settings.py` |
| F-4 | conf 节名 `[storage]+[s3]` 不识别 | 改 `[block_backend]+[commit_object_backend]+[fs_object_backend]` 三节,详 §配 S3 backend |
| F-5 | Pro seahub 缺 boto3 | 容器内 `pip install boto3 botocore`,或自定义 Dockerfile |
| F-6 | 默认端口 8081/8083/9000/9001 可能不在云安全组 | `.env` 默认搬 6000-7000;MinIO S3 API 不外暴露 |

## 架构

```
用户 → Seafile Pro(端口 ${SEAFILE_PORT})→ S3 API → MinIO(docker network 内)→ ZFS dataset A
                                              │
                                              └─ bucket event(commit/ 前缀)→ FastAPI 旁路(MS-FB 协议)→ ffmpeg → dataset B 代理版
```

## 启动

```bash
# 1. 准备 env(在 ../poc/ 根目录)
cp ../.env.example ../.env
vim ../.env
# 关键变量:
#   SEAFILE_DB_PASSWORD / SEAFILE_ADMIN_* / SEAFILE_HOST / SEAFILE_PORT
#   MINIO_ROOT_USER / MINIO_ROOT_PASSWORD / MINIO_CONSOLE_PORT
#   MINIO_DATA_DIR=${DATA_ROOT}/minio
#   MINIO_WEBHOOK_ENDPOINT=http://host.docker.internal:8090/(FastAPI 旁路;早期可指 echo)

# 2. 拉镜像 + 起容器(使用 --env-file 给 docker-compose 读)
docker compose --env-file ../.env up -d

# 3. 等 init(MinIO ~30s,Seafile MC 首启 ~5min:db 建表 + 自动配置)
docker compose logs -f seafile        # 观察 "Successfully created seafile admin" + "Seahub is started"
#   (如果不是 Pro image,会看到 "Error happened during creating seafile admin" — F-1 未修时常见,
#    确认用了 mariadb:10.11 image 即可)

# 4. 在 MinIO 里建 bucket + 配 bucket event
docker run --rm --network seafile_seafile-net \
  -e MC_HOST_local="http://${MINIO_ROOT_USER}:${MINIO_ROOT_PASSWORD}@seafile-minio:9000" \
  minio/mc:latest mb -p local/seafile-blocks
docker run --rm --network seafile_seafile-net \
  -e MC_HOST_local="http://${MINIO_ROOT_USER}:${MINIO_ROOT_PASSWORD}@seafile-minio:9000" \
  minio/mc:latest event add local/seafile-blocks arn:minio:sqs::seafile:webhook \
    --event put --prefix commits/
# 只订阅 commits/ 前缀的 PUT(v0.5 §3.4 — commit object 是 Seafile "新版本就绪" atomic 信号)
```

## 配 S3 backend(F-4)

⚠️ env 注入不被 Seafile parse,首启后**手编 `seafile.conf`**;Seafile 必须是 **Pro Edition**(CE 不带 S3 code path,F-X)。

```bash
# 装 boto3(F-5),Pro seahub 用
docker exec seafile pip install boto3 botocore

# 在 host 上构造 conf 节,然后 docker cp 进去
cat >> /tmp/s3-backend.conf <<EOF

[block_backend]
name = s3
bucket = seafile-blocks
key_id = ${MINIO_ROOT_USER}
key = ${MINIO_ROOT_PASSWORD}
host = seafile-minio:9000
use_v4_signature = true
path_style_request = true
use_https = false

[commit_object_backend]
name = s3
bucket = seafile-blocks
key_id = ${MINIO_ROOT_USER}
key = ${MINIO_ROOT_PASSWORD}
host = seafile-minio:9000
use_v4_signature = true
path_style_request = true
use_https = false

[fs_object_backend]
name = s3
bucket = seafile-blocks
key_id = ${MINIO_ROOT_USER}
key = ${MINIO_ROOT_PASSWORD}
host = seafile-minio:9000
use_v4_signature = true
path_style_request = true
use_https = false
EOF

# append 到现有 seafile.conf
docker cp seafile:/shared/seafile/conf/seafile.conf /tmp/seafile.conf.orig
cat /tmp/seafile.conf.orig /tmp/s3-backend.conf > /tmp/seafile.conf
docker cp /tmp/seafile.conf seafile:/shared/seafile/conf/seafile.conf

# restart seafile
docker compose --env-file ../.env restart seafile

# 验证:上传一个测试文件,然后查 bucket
# (省略 admin token + upload-link 流程,见 ../tests/)
docker run --rm --network seafile_seafile-net \
  -e MC_HOST_local="http://${MINIO_ROOT_USER}:${MINIO_ROOT_PASSWORD}@seafile-minio:9000" \
  minio/mc:latest du local/seafile-blocks
# 期望:对象数 > 0,容量 ~= 上传文件总大小
# KO criterion:如果上传后 bucket 仍 0 对象 → 没用 Pro image,或 conf 改后没 restart
```

## 5. 浏览器登录

```bash
open http://${SEAFILE_HOST}:${SEAFILE_PORT}    # 默认 :6083(F-6)
# SEAFILE_ADMIN_EMAIL / SEAFILE_ADMIN_PASSWORD 登录
```

## 关停 / 重置

```bash
docker compose --env-file ../.env down                  # 容器关停;volumes + ${MINIO_DATA_DIR} 保留
docker compose --env-file ../.env down -v               # 删 named volumes;MinIO host bind mount 保留
rm -rf ${MINIO_DATA_DIR}                                 # 真清空(慎,丢所有 blocks)
```

## 灌数据集

Seafile 不像 NC 可以 `cp` 文件到 datadirectory + scan。Seafile 必须**通过 API 上传**:

| 方式 | 描述 |
| --- | --- |
| (A) seafile-cli 命令行(推荐 PoC) | `seaf-cli sync <local-dir> <library-id>` |
| (B) WebDAV (seafdav) | `curl -X PUT https://${SEAFILE_HOST}/seafdav/<library>/<path>` 逐文件 |
| (C) Web UI(适合 sanity check) | 浏览器拖拽 |
| (D) `seaf-fsck` 导入 | 实操少,不推荐 PoC |

[Issue #23](https://github.com/kevinfitzroy/rushes-lab/issues/23) 待办之一:**敲定 50w 文件的灌数据工程路径** + 实测耗时。

## 7 项 PoC 验收(等机器到位 + Pro license 后跑)

按 [v0.5 §10.1](../../../rushes-spec/material-storage/research/file-management-system.md) + 用户决策 §4:

| # | 验证项 | 判定标准 |
| --- | --- | --- |
| V1 | Seafile + 本地 MinIO(S3 backend)部署 | 能正常创建库、上传、下载、同步 |
| V2 | 桌面同步客户端体验 | 剪辑师日常上传下载流程顺畅 |
| V3 | seafdav 下载性能 | <1 GB 文件 localhost 下载耗时 |
| V4 | MinIO bucket notification 可达性 | commit event 能否正常推送到 FastAPI |
| V5 | commit → event → seafdav 下载 → ffmpeg 转代理 全链路 | 端到端延迟可接受 |
| V6 | 大量文件场景下的 Web UI 响应 | 10 万文件级目录浏览不卡 |
| V7 | 异地同步(Seafile 原生联邦 / rclone 补充) | 跨办公室同步可行性 |

## 资源建议

| 数据集 | 推荐 RAM | 推荐 CPU | 磁盘 |
| --- | --- | --- | --- |
| 1k 文件(Stage 1 sanity) | 2 GB | 2 核 | 10 GB |
| 50w 文件 | 8 GB | 4 核 | 200 GB(blocks 容量 = 文件总 size,加少量元数据)|
| 100w 文件 | 8-16 GB | 4 核 | 400 GB+ |

**资源比 NC 显著低**(NC 同等规模需 16GB+ RAM)— 这是 advisor 推 Seafile 的核心理由之一。

## 关联

- [v0.5 §3.2 Seafile Pro + MinIO 分层](../../../rushes-spec/material-storage/research/file-management-system.md)
- [v0.5 §6.3 P3-P8 + F-X + F-1~F-6 实测约束](../../../rushes-spec/material-storage/research/file-management-system.md)
- [v0.5 §10.1 PoC 任务表](../../../rushes-spec/material-storage/research/file-management-system.md)
- [ADR-0003 Seafile only PoC 决策](../../../rushes-spec/material-storage/decisions/0003-seafile-only-poc.md)
- [Seafile setup_with_s3](https://manual.seafile.com/latest/setup/setup_with_s3/)
- [MinIO bucket notification](https://min.io/docs/minio/linux/administration/monitoring/bucket-notifications.html)
- [Seafile CE vs Pro 对比](https://www.seafile.com/product/private_server/)(v0.5 加,F-X 来源)
- [feishu Issue #24 Seafile 集成预备](https://github.com/kevinfitzroy/rushes-lab/issues/24)(OAuth2 SSO + 下载审批桥接)

## 待 PoC 验证 / TODO

- [ ] 拿到 Seafile Pro license + 镜像,docker-compose.yml 把 image 换成 `seafileltd/seafile-pro-mc:<ver>`
- [ ] 验证 Pro 版 S3 backend 生效:上传后 bucket 有对象
- [ ] MinIO bucket event 在 Seafile 高频小对象 PUT 下的实测吞吐(commits 频率 ≈ 用户 commit 频率,blocks PUT 频率高 N 倍)
- [ ] `path_style_request = true` 对 MinIO 默认配置是否必要(v3 / v4 签名差异)
- [ ] FastAPI 旁路收到 commit event 后,**怎么拿"哪些文件被改了"**:走 `/api/v2.1/repos/<id>/commits/<commit_id>/dirents/` 还是 `seafdav PROPFIND`?待实测
- [ ] 主动转码代理版 e2e:50TB 原片 → ~2TB 代理版(720p H.264)的容量假设是否成立(实际取决于 GOP 长度 + bitrate 选择)
