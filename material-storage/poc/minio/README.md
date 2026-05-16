# PoC — Pigsty MinIO fork(ADR-0005 Phase A)

> 验证 [ADR-0005](../../../rushes-spec/material-storage/decisions/0005-drop-seafile-middle-layer-minio-only.md) §9 Phase A 出口条件 + §11.2 Gap 9(bucket notification 可靠性)。

## 范围(Phase A)

| 验收点 | 对应 Gap |
| --- | --- |
| Pigsty MinIO fork 部署可用(API + Console) | — |
| Bucket notification → FastAPI webhook 链路通 | Gap 9 |
| presigned URL 上传 / 下载 OK | Gap 1 / Gap 2 前置 |
| (Phase A 边界外) uppy 100GB+ 文件实测 | Gap 2(本 PoC 留接口,真实测试见后续) |

## 部署(8.156.34.238 实测过)

服务器:`8.156.34.238`(阿里云,安全组开放 6000-7000;详见 `server.md` workspace 根)。

```bash
# 1. 同步本目录到服务器
scp -r ./ root@8.156.34.238:/root/poc-pigsty-minio/

# 2. 启动
ssh root@8.156.34.238 'cd /root/poc-pigsty-minio && docker compose up -d'

# 3. 等容器 healthy(~10s)
ssh root@8.156.34.238 'docker ps --filter name=poc-'

# 4. Console
# 浏览器开 http://8.156.34.238:6101  user=minioadmin pass=minioadmin-poc-2026
```

## 端口分配(与现有 Seafile PoC 不冲突)

| 端口 | 用途 | 备注 |
| --- | --- | --- |
| 6100 | MinIO S3 API(host:9000)| 给外部 SDK / mc / uppy 直传 |
| 6101 | MinIO Web Console(host:9001)| admin / 排错 |
| (container 内 8000) | FastAPI webhook receiver | 不外暴露,容器间访问 |

> 占用情况(2026-05-16):6083(seafile)/ 6901(seafile-minio)— 旧 Seafile PoC 容器,**保留不动**作为历史对比。

## 创建 bucket + 配 notification

```bash
ssh root@8.156.34.238 bash <<'EOF'
docker exec poc-pigsty-minio mc alias set local http://localhost:9000 minioadmin minioadmin-poc-2026
docker exec poc-pigsty-minio mc mb local/rushes-poc
docker exec poc-pigsty-minio mc event add local/rushes-poc arn:minio:sqs::RUSHES:webhook --event put,delete
docker exec poc-pigsty-minio mc event list local/rushes-poc
EOF
```

## 测试链路通

```bash
ssh root@8.156.34.238 bash <<'EOF'
# 1. 上传一个文件
echo "hello rushes lab $(date)" > /tmp/poc-test.txt
docker cp /tmp/poc-test.txt poc-pigsty-minio:/tmp/
docker exec poc-pigsty-minio mc cp /tmp/poc-test.txt local/rushes-poc/

# 2. 看 webhook 是否收到
sleep 2
docker logs poc-webhook --tail 5
docker exec poc-webhook curl -s http://localhost:8000/events
EOF
```

**期望**:webhook stdout 出现 `s3:ObjectCreated:Put bucket=rushes-poc key=poc-test.txt size=...`,`/events` 返回 events 列表。

## Phase A.2 — 6 个 scenarios(2026-05-16 实测,server-side curl/mc 全验)

| # | Scenario | 状态 | 说明 |
| --- | --- | --- | --- |
| **A** | alice(admin)全 bucket RW | ✅ | ls 5 bucket / PUT `private-sensitive/` / GET 回 |
| **B** | bob(limited)权限边界 | ✅ | 只看到 public;拒绝写 `private-*` / 跨用户 `incoming/alice/`;读 `public` OK;读 `private-internal` 403 |
| **C** | 模拟审批 — alice 签 presigned GET URL 给 bob | ✅ | `mc share download --expire 5m` 返完整 sig v4 URL;**注 caveat P-10** |
| **D** | uppy 5-endpoint multipart 端到端(50 MiB / 2 parts) | ✅ | POST `/s3/multipart` → GET sign part(×2) → PUT 25 MiB(×2)→ POST complete → ETag `e9cc...-2` 落库;**webhook 收到** `CompleteMultipartUpload bucket=incoming key=uppy-test%2F...` |
| **E.1** | 正常完成无 orphan | ✅ | 5 个 bucket `mc ls --incomplete --recursive` 全空 |
| **E.2** | DELETE abort 清理 | ✅ | `POST /s3/multipart` + `DELETE /s3/multipart/{id}` → `{aborted: true}` |
| **F** | 1 GB 大文件 multipart + webhook | ✅ | mc 自动 multipart(16 MiB part × 64),5 s 完成;webhook 收到 `bucket=incoming key=big-1g-v2.bin size=1073741824` |

**Phase A.2 出口条件 ✅ 全部通过**(浏览器实测 uppy UX / 100GB+ 真实场景 / 断网恢复留作 follow-up,需用户参与)。

## Phase A.3 — nginx 反代 80 公网直连(2026-05-16 实测)

| 验证 | 状态 |
| --- | --- |
| Local(server-side) curl `http://localhost/health` | ✅ |
| **跨境(Claude Code → 阿里云 8.156.34.238)curl `/health`** | ✅ 24ms |
| **公网 跨境完整 uppy multipart(create / sign / PUT / complete)经 nginx** | ✅ ETag `e9cc...-2`,webhook `s3:ObjectCreated:CompleteMultipartUpload bucket=incoming key=uppy-test%2Fnginx-test-50m.bin` |
| MinIO Console `http://8.156.34.238/console/` | ✅ 200 |
| `http://8.156.34.238/uppy/` → uppy 前端 | ✅ |

→ **公网直连完全 work,SSH tunnel 退役为 fallback**。详 P-14 配置。

## Finding P-8 ~ P-13(2026-05-16,Phase A.2 实测追加)

| # | Finding | 影响 | 处理 |
| --- | --- | --- | --- |
| **P-8** | **MinIO bucket notification 必须 per-bucket 配**(`mc event add local/<bucket>`)而非全局 | 新建 bucket 不会自动继承 webhook,易漏 | 部署脚本 / 业务后端创建 bucket 时**同步注册 event**;监控:定时 `mc event list` 对账 |
| **P-9** | MinIO IAM:user = access key 本身(非 username),`mc admin user add <accesskey> <secret>` 3 参数(若多写 1 个会被当 secret + extra arg 报 USAGE);policy 用 JSON 文件 + `mc admin policy create local <name> <file.json>` + `mc admin policy attach local <policy> --user <accesskey>` | 易踩坑(误以为 user/secret 分离命名) | 文档化命令模板;policy JSON 用 IAM-style `Statement / Effect / Action / Resource`,支持 prefix-based 隔离(`incoming/bob/*` for bob own,Condition `s3:prefix` 控 ListBucket 可见性) |
| **P-10** | **Presigned URL sig v4 把 host 头进 canonical request,host:port 必须 客户端 与 签发时 一致**;否则 `SignatureDoesNotMatch` 403 | mc share download 默认用 alias endpoint 签;若客户端从别的 host 访问(SSH tunnel / 公网 / proxy)→ 全失败 | **presigner 用双 boto3 client** :`s3_internal` (docker DNS) 调 admin API(create/complete/abort/list);`s3_signer` (公网 host) 仅签 URL,不发请求 — 签出的 URL host = 客户端视角 host,签名匹配。MINIO_PUBLIC_HOST 环境变量配置可达 host(SSH tunnel = `http://localhost:6100`;直连 = `http://<server-ip>:6100`)|
| **P-11** | **Webhook 事件 key 是 URL-encoded**(`/` → `%2F`),例 `bucket=incoming key=uppy-test%2Fuppy-test-50m.bin` | audit handler / 业务消费者直接用 key 查会 miss(URL-encoded ≠ 实际 object key) | 业务后端 webhook handler 必须 `urllib.parse.unquote(key)` 后再用 |
| **P-12** | **Python 3.14-alpine 是 latest 但 boto3 / urllib3 没 prebuild wheel,pip install 从源码 build 卡 > 5 min**;3.12-alpine 有 prebuild,< 60 s 完成 | 容器启动延迟 → 误判失败 | pin `python:3.12-alpine`;pip mirror `https://mirrors.aliyun.com/pypi/simple/`(env `PIP_INDEX_URL`);mount pip cache volume 避免每次 install |
| **P-13** | **阿里云安全组实际开放 22/80/443**(6000-7000 全段 1001 端口阻断,与 server.md 描述不一致)| user-facing 必须走 80/443 | **方案**(P-14):nginx 反代 80 → MinIO Console + uppy + presigner + S3 API,公网直连不需 SSH tunnel(2026-05-16 实测 24ms 延迟跨境通) |
| **P-14** | **nginx 反代 MinIO + sig v4 host 一致性** — 三联配置缺一不可:(1) MinIO `MINIO_SERVER_URL=http://<public-host>` 让 MinIO 签 presigned URL 用公网 host;(2) `MINIO_BROWSER_REDIRECT_URL=http://<public-host>/console` 让 Console UI base URL 正确;(3) presigner `MINIO_PUBLIC_HOST=http://<public-host>` 让 boto3 s3_signer client 签 URL host 与浏览器访问一致;(4) nginx `proxy_set_header Host $host` 保留浏览器 host 头给后端验签 | 任一缺 → SignatureDoesNotMatch 403 | 完整配置见 `nginx/default.conf` + docker-compose env;实测 uppy 5-endpoint 多 part 上传通过 80 端到端 OK(50 MiB,2 parts,ETag `e9cc...-2`,webhook 触发)|
| **P-15** | docker compose `depends_on` 必须用 **service name**(yaml 顶级 key),不是 `container_name`(单独字段) | `depends_on: poc-pigsty-minio` → "depends on undefined service" 错 | 改 `depends_on: pigsty-minio`;container_name 用于 docker ps 显示 + DNS,**与 service name 解耦** |

## 用户访问指南(2026-05-16 后:**公网直连**,无需 SSH tunnel)

阿里云安全组实测**只对 22/80/443 开放**(6000-7000 全段阻断,详 P-13)。改用 nginx 反代 80,所有 user-facing endpoints **公网可达**:

| URL | 用途 |
| --- | --- |
| **http://8.156.34.238/** | 自动 redirect → `/uppy/` |
| **http://8.156.34.238/uppy/** | uppy 大文件上传前端(拖拽即用,< 100 MiB single PUT,≥ 100 MiB multipart)|
| **http://8.156.34.238/console/** | MinIO Console — user `minioadmin` pass `minioadmin-poc-2026` |
| http://8.156.34.238/health | presigner health(JSON)|
| http://8.156.34.238/s3/multipart* | uppy AwsS3 plugin API endpoint(presigner)|
| http://8.156.34.238/`<bucket>`/`<key>`?X-Amz-... | MinIO S3 API,presigned URL 直传通道(nginx 反代 → MinIO :9000)|

**SSH tunnel 仍保留作 fallback**(若 nginx 出问题或需要直接访问 6100/6101):
```bash
ssh -L 6100:localhost:6100 -L 6101:localhost:6101 -L 8080:localhost:8080 root@8.156.34.238
```

## 后续(超出 Phase A 验收)

- **浏览器实测 uppy UX**(Gap 2):用户走 SSH tunnel,跑大文件(尤其 100 GiB+),验证进度条 / 浏览器关闭恢复 / 断网重连(uppy 内置 retry + listParts)— **需要用户参与**
- **MinIO site replication 灾备 PoC**:需要第二台机或第二个 docker compose project,后续 Phase
- **presigned URL 撤销 black list**(Gap 1):需要业务后端 + FastAPI 代理层校验(stateless presigned 不可直接撤,要黑名单兜底)
- **真实负载** scenario:1k user 并发 + 100 万对象 + 50TB 数据 — 留生产化阶段
- **配阿里云安全组**(P-13)或 nginx 反代 6XXX → 80/443,以摆脱 SSH tunnel 限制

## Finding(2026-05-16,Phase A 部署 + 端到端链路实测)

> 类比 ADR-0003 §配套实施 finding 的 F-1~F-6 格式;序号 **P-1~P-7**(P = Pigsty)。

| # | Finding | 影响 | 处理 |
| --- | --- | --- | --- |
| **P-1** | `pgsty/minio:latest` image 在 Docker Hub 直接可拉(~55MB 压缩);Pigsty 维护链路通畅 | 部署成本极低 | 直接 `docker pull pgsty/minio` |
| **P-2** | Docker Compose v5.1.3 配置语法兼容,无 F-1/F-2 同类问题 | 无 | — |
| **P-3** | **阿里云从 dockerhub 拉 `python:3.12-slim` 等"主流但非冷门"image 会 hang/慢** | webhook 容器卡死,排查耗时 | 用 `python:3-alpine`(小 + 常用,daocloud 镜像有 cache);webhook 用 **Python stdlib `http.server` + 无 pip install**;若需 FastAPI 生产化要么配 docker registry mirror 要么自建 base image |
| **P-4** | `minio/mc` image entrypoint 是 mc 本身,**没有 bash**(基于 distroless / scratch?)| 链式命令需 `--entrypoint sh -c "..."`(alpine 有 sh,scratch 没,本 case work) | 文档化:`docker run --rm --network <net> --entrypoint sh minio/mc:latest -c "mc alias set ... && mc mb ... && mc event add ..."` |
| **P-5** | `pgsty/minio` image **不带 mc CLI**,也不带 `which / wget / curl` 等基础工具 | docker exec 进容器没 mc 可用 | mc 用单独 `minio/mc` 容器(同 docker network)调;运维脚本不依赖容器内 shell 工具 |
| **P-6** | **Multipart upload 事件类型不同**:小文件 `s3:ObjectCreated:Put`,大文件(mc 默认 ≥ 64MB)`s3:ObjectCreated:CompleteMultipartUpload` | material-storage webhook handler 必须**两种事件名都处理**,否则大文件上传不会触发旁路 worker(§11.2 Gap 9) | webhook router 用 `s3:ObjectCreated:*` 通配;audit `event_type` 同时记录细分类型;dedup_key 用 `<source>:<request_id>` 兼容两条路径 |
| **P-7** | 本机 LAN 性能:50MB upload 317 MiB/s,200MB upload 220 MiB/s,webhook 触发**几乎实时**(< 100ms 端到端)| 本机/同机房场景延迟可忽略 | 异地 / WAN 场景 + 100GB+ 文件 + uppy 浏览器直传 multipart 延迟需另外 PoC(Gap 2) |

## 验收结论(Phase A 出口条件,ADR-0005 §9)

| 出口条件 | 状态 |
| --- | --- |
| Pigsty MinIO fork 部署可用(API + Console)| ✅ 6100 / 6101 端口 healthy |
| MinIO bucket notification → FastAPI webhook 链路通 | ✅ Put / CompleteMultipartUpload 均触发 |
| 100GB+ 文件上传可靠(浏览器 + 网络抖动)| 🟡 本机大文件 OK;真实场景需另外 PoC(见 P-7) |

**→ Phase A 核心出口条件 ✅ 通过**;100GB+ uppy 真实场景留作 Phase A.2 / Phase B 跑(Gap 2 PoC)。

## 关联

- ADR-0005 §9 Phase A 实施 / §11.2 Gap 1/2/9
- 历史对比:`../seafile/`(ADR-0003 Seafile Pro PoC scaffold)
- 上游 PR #33 / Issue #34 / #35 / #36
