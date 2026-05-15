# seafile/ — Seafile + 本地 MinIO PoC 路线(v0.4 主推)

落地 [v0.4](../../../rushes-spec/material-storage/research/file-management-system.md) §3.2 分层。覆盖 issue [PoC-Seafile] 的部署骨架(性能压测脚本另立,见 `../tests/`)。

## 架构

```
用户 → Seafile(端口 ${SEAFILE_PORT})→ S3 API → MinIO(端口 ${MINIO_API_PORT})→ ZFS dataset
                                              │
                                              └─ bucket event → FastAPI 旁路(MS-FB 协议)
```

## 启动

```bash
# 1. 准备 env(在 ../poc/ 根目录)
cp ../.env.example ../.env
vim ../.env
# 关键变量:
#   MINIO_ROOT_USER / MINIO_ROOT_PASSWORD       # MinIO 管理凭据
#   MINIO_DATA_DIR=${DATA_ROOT}/minio            # MinIO 数据物理位置
#   SEAFILE_DB_PASSWORD / SEAFILE_ADMIN_*        # Seafile 启动凭据
#   SEAFILE_HOST=<your-host-or-ip>               # 浏览器访问域
#   MINIO_WEBHOOK_ENDPOINT=http://...:8090/      # FastAPI 旁路接收 URL(PoC 早期可指 echo server)

# 2. 拉镜像 + 起容器
docker compose up -d

# 3. 等 init(MinIO ~30s,Seafile MC 首启 ~5min:db 建表 + 自动配置)
docker compose logs -f seafile        # 观察 "Seahub is started" / "Seafile server started"

# 4. 在 MinIO 里创建 Seafile bucket + 配 bucket event
docker exec -it seafile-minio sh
  mc alias set local http://localhost:9000 $MINIO_ROOT_USER $MINIO_ROOT_PASSWORD
  mc mb local/seafile-blocks
  mc event add local/seafile-blocks arn:minio:sqs::seafile:webhook \
    --event put --prefix commits/
# 注:只订阅 commits/ 前缀的 PUT(v0.4 §3.4 Seafile MinIO event 过滤约定 —
# commits 是 Seafile "新版本就绪" 的 atomic 信号)

# 5. 改 Seafile 配置走 S3 backend
# (docker-compose 里 env 注入有时不生效;退而求其次手编 conf 文件)
docker exec -u root seafile bash
  vim /shared/seafile/conf/seafile.conf
  # 加 [storage] type = s3,[s3] 各项指 seafile-minio:9000 / seafile-blocks / 凭据
  # 然后重启容器
docker compose restart seafile

# 6. 浏览器进
open http://${SEAFILE_HOST}:${SEAFILE_PORT}
# 用 SEAFILE_ADMIN_EMAIL / SEAFILE_ADMIN_PASSWORD 登录
```

## 关停 / 重置

```bash
docker compose down                  # 容器关停;volumes + ${MINIO_DATA_DIR} 保留
docker compose down -v               # 删 named volumes(seafile-data + mysql);MinIO 数据保留(它在 host bind mount 上)
rm -rf ${MINIO_DATA_DIR}             # 真清空(慎,丢所有用户上传的 blocks)
```

## 灌数据集

Seafile 不像 NC 可以 `cp` 文件到 datadirectory + scan。Seafile 必须**通过 API 上传**:

| 方式 | 描述 |
| --- | --- |
| (A) seafile-cli 命令行(推荐 PoC) | `seaf-cli` 包含在 Seafile 容器中或独立装;`seaf-cli sync <local-dir> <library-id>` |
| (B) WebDAV (seafdav) | `curl -X PUT https://${SEAFILE_HOST}/seafdav/<library>/<path>` 逐文件 |
| (C) Web UI(适合小规模 sanity check) | 浏览器拖拽上传 |
| (D) `seaf-fsck` 导入(对应历史导出,反向)| 实操少,不推荐 PoC 用 |

issue [PoC-Seafile] 待办之一:**敲定 50w 文件的灌数据工程路径** + 实测耗时。

## 性能验收(等机器到位后跑)

按 v0.4 §10.1 PoC 任务表:

- 部署 Seafile + MinIO,关闭内置视频缩略图 ✓(本目录配置已做)
- 灌入 50w 合成数据集(via API)
- **MinIO bucket notification 在 50w 并发 PUT 下不丢、可靠重投**(MinIO 内置 webhook 重试机制要验证)
- **Seafile commit object 顺序保证**(blocks 先 PUT,commit 对象最后 PUT)— 看代码路径或实测
- **用户上传 mp4 → FastAPI 拿到完整文件 P50/P95 延迟**(MinIO event → Seafile REST → seafdav 三步链路)
- 资源占用对比 NC(RAM / CPU / 磁盘 IO)
- Seafile 桌面 / 移动客户端兼容性
- 与 bridge OAuth2 / OIDC 集成 e2e(配合 ../tests/ + feishu-integration)

## 资源建议

| 数据集 | 推荐 RAM | 推荐 CPU | 磁盘 |
| --- | --- | --- | --- |
| 1k 文件(Stage 1 sanity) | 2 GB | 2 核 | 10 GB |
| 50w 文件 | 8 GB | 4 核 | 200 GB(blocks 容量 = 文件总 size,加少量元数据)|
| 100w 文件 | 8-16 GB | 4 核 | 400 GB+ |

**Seafile 路线资源比 NC 显著低**(NC 同等规模需 16GB+ RAM)— 这是 advisor 推 Seafile 的核心理由之一。

## 关联

- [v0.4 §3.2](../../../rushes-spec/material-storage/research/file-management-system.md) Seafile + MinIO 分层
- [v0.4 §6.3](../../../rushes-spec/material-storage/research/file-management-system.md) P3-P8 Seafile/MinIO 实施约束 + 待 PoC 实测项
- [v0.4 §10.1](../../../rushes-spec/material-storage/research/file-management-system.md) PoC 任务表
- [Seafile setup_with_s3 官方文档](https://manual.seafile.com/latest/setup/setup_with_s3/)
- [MinIO bucket notification](https://min.io/docs/minio/linux/administration/monitoring/bucket-notifications.html)

## 待 PoC 验证 / TODO

- [ ] `seafileltd/seafile-mc:13.0` 镜像是否支持 S3 backend env 注入,还是必须改 conf 文件
- [ ] MinIO bucket event 在 Seafile 高频小对象 PUT 下的实测吞吐(commits 频率 ≈ 用户 commit 频率,blocks PUT 频率高 N 倍)
- [ ] `seafile.conf [s3] path_style_request = true` 对 MinIO 默认配置是否必要(v3 / v4 签名差异)
- [ ] FastAPI 旁路收到 commit event 后,**怎么拿"哪些文件被改了"**:走 `/api2/repos/<id>/commits/<commit_id>/dirents/` API?还是 `seafdav PROPFIND`?待实测
