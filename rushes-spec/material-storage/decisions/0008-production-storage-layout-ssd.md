# ADR-0008: 生产存储布局 —— SSD/HDD 分层(2TB SSD + 机械盘)

- **状态:** accepted
- **日期:** 2026-08-09
- **决策者:** user + material-storage agent
- **关联:**
  - [ADR-0007](0007-drop-feishu-self-built-identity.md)(生产初版定位:浏览/检索速度是核心 UX)
  - [`../ROADMAP.md`](../ROADMAP.md) 生产部署清单
  - 容量上限假设:[`../research/file-management-system.md`](../research/file-management-system.md) §1(100TB / 50-100 万文件)

## 背景

- 生产服务器(局域网)存储形态:**机械硬盘(HDD)为主存储 + 1 块 2TB SSD**。
- 2026-08-09 代码核实:**代码对 SSD 零感知** —— 分层完全由部署期卷挂载决定:

| 数据 | 现状位置 | 证据 |
| --- | --- | --- |
| 原片(视频/图片) | MinIO 单卷 `./data:/data` | `poc/minio/docker-compose.yml:29` |
| 缩略图 | 与原片**同 bucket**(`thumbnails/{asset_id}.jpg` 前缀) | `workers/main.py:100` |
| Postgres(元数据) | docker named volume `ms-db-data`(落 OS 盘) | `api/docker-compose.yml:19` |
| Redis / OpenFGA PG | named volume(落 OS 盘) | `api/docker-compose.yml:32`、`poc/minio/docker-compose.yml:43` |

- 方向校正后(ROADMAP 2026-08-09 节),**列表浏览与盲搜的响应速度是核心 UX** —— 缩略图与元数据正是热点,值得确定性分层而非靠页缓存运气。

## 容量测算(2TB SSD 怎么花)

| 数据 | 量级估算 | 放 SSD? |
| --- | --- | --- |
| PG 元数据 + 索引(含盲搜 pg_trgm) | 100 万 asset ≈ 个位数 GB | ✅ |
| 缩略图(1024px jpeg,100-300KB/张) | 100 万 asset ≈ 100-300 GB | ✅ 全量装得下 |
| Redis / OpenFGA / OS / docker 镜像 / 日志 | 数十 GB | ✅ |
| 原片(视频为主) | TB 级起步,规划上限 100TB | ❌ HDD |

结论:2TB SSD 装全部"热而小"的数据占用 <25%,余量充足;原片走 HDD。

## 候选

| 方案 | 内容 | 评价 |
| --- | --- | --- |
| A 纯卷放置 | SSD:OS/PG/Redis/OpenFGA;HDD:MinIO 全部(原片+缩略图同卷) | 零代码;但缩略图在 HDD,浏览速度靠页缓存运气 |
| B A + 缩略图拆 SSD | 第二个 MinIO 容器(SSD 卷)专放缩略图 bucket;settings/presign/worker 小改动 | 浏览速度确定性保证;改动 bounded;**采纳** |
| C host 级透明缓存 | ZFS special vdev(+ `special_small_blocks`)/ LVM cache / bcache,SSD 作 HDD 缓存层 | 应用零感知,能兜"近期上传回读";依赖 OS/FS 选型与运维熟悉度;**可选 P2** |
| D MinIO server pools 原生分层 | 多池 tiering | 复杂度远超单租户需求,**拒绝** |

## 决策

1. **卷放置(P0,纯部署,零代码):** SSD 挂 `/ssd` —— OS、docker root、PG(`ms-db-data` 改 bind mount)、Redis、OpenFGA PG;HDD 挂 `/data` —— MinIO 原片数据。
2. **缩略图拆分到 SSD(P1,小代码改动):** 第二个 MinIO 容器(SSD 卷,独立 bucket,如 `ms-thumbs`)。改动点三处:`settings.py` 加 thumbnail endpoint/bucket;`workers/main.py` 缩略图上传目标;`services/presign.py` 缩略图签名走 SSD endpoint。新部署无存量迁移;缩略图本就"短 presign 不过 OpenFGA"(既有决策),拆分不影响权限语义。
3. **host 级缓存(P2,可选,不阻塞上线):** provisioning 若选 ZFS → special vdev + `special_small_blocks=128K`(小文件/元数据自动上 SSD);否则 LVM cache / bcache。观察 HDD 读热点后再定。
4. **明确不做:** 应用内 tiering 逻辑;MinIO server pools;上传暂存分层(multipart 直写 HDD,顺序写无瓶颈)。

## 影响

- **compose(部署侧,随内网生产 compose 一并落地):** `poc/minio/docker-compose.yml` MinIO data 卷指向 HDD 挂载点 + 新增缩略图容器;`api/docker-compose.yml` PG/Redis 卷改 SSD bind mount。
- **代码:** 仅决策 2 的三处小改动;`.env.example` 补缩略图 endpoint 示例。
- **备份:** 分层与备份策略对齐 —— SSD 侧(PG dump + 缩略图)小,可高频;HDD 原片大,低频 `mc mirror`(ROADMAP 灾备项)。
- **监控/降级:** SSD 水位 80% 告警;缩略图 bucket 溢出时降级开关 = env 指回原 bucket(HDD),无需数据迁移。
- **风险:** 第二个 MinIO 容器多一个进程与 endpoint(运维 +1);缩略图 endpoint 配错 → 签名 host 不一致(P-10 类坑),进部署 checklist。

## 变更日志

- 2026-08-09:accepted(user ratify)
