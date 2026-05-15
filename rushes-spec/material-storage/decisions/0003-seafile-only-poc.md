# ADR-0003 — PoC 收敛到 Seafile only(需 Pro Edition)

- Status: accepted
- Date: 2026-05-15
- Supersedes: v0.4 PoC 二选一(NC + Seafile)的"两路线并行"前提
- Related:
  - [file-management-system.md v0.5](../research/file-management-system.md)
  - [decisions/0002-feishu-contacts-as-identity-source.md](./0002-feishu-contacts-as-identity-source.md)
  - [feishu/decisions/0002-bridge-as-oidc-provider.md](../../feishu/decisions/0002-bridge-as-oidc-provider.md)
  - Issue #23(PoC-Seafile 更新),Issue #12(PoC-NC 关闭),Issue #24(feishu 集成预备)

## 决策结论

PoC 范围从 **NC + Seafile 二选一**,收敛为 **Seafile (Pro Edition) 唯一**。

- Nextcloud 路线退出首批 PoC → Issue #12 关闭
- oCIS 保持 P1 长期方向 → Issue #13 不动(priority:p1)
- Seafile Pro license 申请于 2026-05-16 联系销售,本 ADR 假定 Pro 可获取

## 触发本次收敛的两条独立证据

### 证据 1 — NC 架构级风险(同 advisor + 文献)

`oc_filecache` 膨胀(Nextcloud issue #7312)是架构级问题,**50-100 万文件量级不可调和**:即使调优 PG / 定期 pg_repack,膨胀路径仍存在(预览生成 → filecache 膨胀 → 桌面同步变慢 → WebDAV 吞吐下降),与本项目数据增长方向(~100 TB 短视频原片,文件总数百万级)直接冲突。

详见用户决策文档第六节(本 ADR §6)与 v0.5 §11 NC 归档。

### 证据 2 — 2026-05-15 PoC 实测 — Seafile CE 不支持 S3 backend

部署机 `8.156.34.238`(Ubuntu 22.04,8 核 / 14 GB / 2 TB NVMe)实测:

| 检查 | 结果 |
| --- | --- |
| `seafileltd/seafile-mc:latest` 实际版本 | **11.0.13** |
| `strings /opt/seafile/.../seaf-server` `\| grep -iE "s3\|aws\|amazon"` | **无任何匹配** |
| `seafile.conf` 加 `[block_backend] name = s3` + S3 节后上传 1 MB 文件 | blocks 仍写入 `/shared/seafile/seafile-data/storage/`,**MinIO bucket 仍 0 对象** |
| Seafile 官方对比页 [seafile.com/product/private_server/](https://www.seafile.com/product/private_server/) | "AWS S3/Ceph/阿里云后端" 列在 **企业版独有功能** |

→ v0.4 §3.2 "Seafile + 本地 MinIO 作 S3 backend" 路线**核心前提失效**,必须升 **Seafile Pro Edition**。

## 三个传统弱点的工程化应对

用户决策文档 §3 完整对比表搬入 v0.5 §3.2(略),摘要如下。

### 弱点 1: 无原生 webhook

- **方案**: MinIO bucket notification (Seafile Pro 写 S3 → commit object PUT → MinIO event webhook → FastAPI)
- **判定**: 不影响评审通过 — async pipeline 场景下事件延迟 +3s 被 AI 打标/转码自身耗时(几十秒至分钟)完全覆盖
- **优势**: commit object 是 atomic 信号(blocks/fs 全写完后才 PUT),天然保证文件完整,比 NC inotify 减少 "等文件写完" 防御代码

### 弱点 2: 无 POSIX 直读

- **方案**: 主动转码 → dataset B 代理版 → POSIX 直读
  - Web 播放/审批播放 → dataset B 代理版(720p H.264 MP4,~10-20 MB/min),零跳转
  - 原片只在 FastAPI 旁路 seafdav 下载时使用一次
- **判定**: 不影响评审通过 — 10 万条短视频原片(50 TB)→ 代理版约 2 TB(~4%),完全可接受
- **关键设计**: 主动转码而非被动 cache(首播延迟、淘汰逻辑、AI pipeline 复用三处都赢)

### 弱点 3: 无 inotify 旁路

- **方案**: MinIO bucket event 替代(commit 对象按 key 前缀过滤,优于 NC 文件路径过滤)
- **判定**: 不影响评审通过 — 信号正确性反而优于 inotify(无中途触发,无队列溢出丢事件)

## PoC 验收清单(用户决策 §4)

7 项验证已搬入 Issue #23 的 acceptance criteria:

1. Seafile + 本地 MinIO(S3 backend)部署 — 能正常创建库、上传、下载、同步
2. 桌面同步客户端体验 — 剪辑师日常上传下载顺畅
3. seafdav 下载性能 — <1 GB 文件 localhost 下载耗时
4. MinIO bucket notification 可达性 — commit event 能正常推 FastAPI
5. commit → event → seafdav 下载 → ffmpeg 转代理 全链路 — 端到端延迟可接受
6. 大量文件场景下 Web UI 响应 — 10 万文件级目录浏览不卡
7. 异地同步(Seafile 原生联邦 / rclone 补充) — 跨办公室同步可行性

## 不采用 NC 的具体理由(用户决策 §6)

1. `oc_filecache` 膨胀(#7312)是架构问题,不是调优能解决
2. 50-100 万文件量级下,NC 已知膨胀路径与本项目数据增长方向直接冲突
3. NC 的 POSIX 直读 + inotify 友好优势,在本项目 async pipeline 场景下价值被稀释
4. Seafile 的块存储 + 原子 commit 在正确性上反而更优

> NC 不是不能跑,而是 "在错误的方向上花精力"——调优 DB、管理 `oc_filecache`、做 `pg_repack` 的计划,这些时间应该花在业务开发上。

## License / Pro 版前提

- Pro license 申请于 **2026-05-16** 联系 Seafile 销售
- 本 ADR 假定 Pro 可获取
- 若 Pro 不可获取 → 重新评估方向,候选(按优先级):
  1. oCIS 提前(把 Issue #13 P1 → P0)
  2. 接受 Seafile CE + local fs + 接受 inotify 回归(放弃 MinIO event 优势)
  3. 商业替代品(MinIO + 自研 Seafile-like 元数据)— 工作量大,不推荐
- 决策结果作为本 ADR 的 amendment 或 ADR-0004 记录

## 配套实施 finding(2026-05-15 部署机 8.156.34.238)

供 PoC scaffold 与 README 复用,生产部署亦需注意:

| # | Finding | 影响 | 处理 |
| --- | --- | --- | --- |
| F-1 | MySQL 8 默认 `caching_sha2_password` 与 seaf-server 内嵌 libmariadb 不兼容 | seaf-server connect MySQL 全失败 → 衍生 admin 创建失败、system repo init 失败 | docker-compose 用 **MariaDB 10.11 LTS**,不要 MySQL 8 |
| F-2 | `seafileltd/seafile-mc:13.0` tag 不存在(daocloud 403) | docker pull 失败 | latest = 11.0.13;Pro 用 `seafileltd/seafile-pro-mc:<ver>` |
| F-3 | `seahub_settings.override.py` 不被 Seafile 自动 import(`settings.py` 只 import `seahub_settings` 和 `local_settings`) | PoC 配置静默失效(`ENABLE_VIDEO_THUMBNAIL = False` 没生效) | 挂载点改名 **`local_settings.py`** |
| F-4 | S3 backend conf 节名 | `[storage]` + `[s3]` 不被 seaf-server 识别 | 正确格式 `[block_backend]` + `[commit_object_backend]` + `[fs_object_backend]`,每节填 `name = s3` + `bucket` + `key_id` + `key` + `host` + `use_v4_signature = true` + `path_style_request = true` + `use_https = false` |
| F-5 | seahub Python 端缺 `boto3` | Pro 版 seahub 启动 ModuleNotFoundError | image 内 `pip install boto3 botocore`,生产用自定义 Dockerfile pin 版本 |
| F-6 | 端口策略 — 部署机 8.156.34.238 阿里云安全组开放 **6000-7000** | 默认 8081/8083/9000/9001 不在开放范围 | PoC 端口搬 6000-7000;MinIO S3 API **不外暴露**(仅 docker network 内访问),Console 走 6901 |

## 关联

- 用户决策文档原文(2026-05-15):"Rushes Lab — Seafile 收敛决策与弱点应对方案"
- v0.5 file-management-system.md(本 ADR 配套修订)
- Issue #12 close(NC 退出 PoC)
- Issue #23 update(PoC-Seafile 加 Pro 需求 + 上述 F-1 ~ F-6)
- Issue #24(feishu agent Seafile 集成预备 — OAuth2 SSO + 审批桥接)
- material-storage/poc/seafile/ scaffold update(MariaDB / local_settings.py / [block_backend] 等)
