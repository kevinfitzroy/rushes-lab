# 调研:文件管理系统选型

> **调研日期:** 2026-05-15
> **版本:** v0.5(PoC 收敛 Seafile only;依赖 Seafile Pro Edition)
> **结论摘要:** 首批 PoC = **Seafile (Pro Edition) + 本地 MinIO 作 S3 backend** 单条路线。NC 退出首批 PoC(架构级 `oc_filecache` 膨胀风险与本项目数据增长方向冲突)。oCIS 维持 P1 长期方向。完整决策依据见 [ADR-0003](../decisions/0003-seafile-only-poc.md)。
> **状态:** PoC 部署阶段(实测发现见 §6.3 F-1~F-6;Pro license 2026-05-16 接洽销售)
> **v0.5 关键变化:** ① NC 路线整体归档 → §11;② Seafile 路线深化(三弱点工程化应对 + 主动转码代理版策略);③ 2026-05-15 实测发现 6 条 F-1~F-6 → §6.3;④ Seafile CE 不支持 S3 backend 的 KO 证据 + 升 Pro 前提。

## 1. 已校准的关键约束

| 维度 | 值 | 来源 |
| --- | --- | --- |
| 总数据量(5 年内) | **100 TB** | 用户口述 2026-05-15 |
| 单文件尺寸 | < 1 GB,以 < 500 MB 为主 | 用户口述 |
| 估算文件数量 | **50 万 - 100 万**(100 TB ÷ 100-200 MB 推算) | 派生 |
| 内容形态 | 短视频成片 + 拍摄原片 都入库 | 用户口述 |
| 工作负载 | 非剪辑挂载;走"下载-剪-回传"或 web 浏览 | 用户口述 |
| 部署形态 | 内网为主,异地访问需要 | v2 文档 |
| 商业付费容忍度 | **0(纯开源)** | 用户口述 |
| 用户规模 | 百人级 | 用户口述 |
| 用户身份源 | **飞书通讯录作 SoT**(2026-05-15 收敛,不再 LDAP/AD) | [ADR-0002](../decisions/0002-feishu-contacts-as-identity-source.md) |
| 审批通道 | **飞书 / Lark** | 由 `feishu-integration` 子项目实施 |
| AI 接入 | 阶段一含 自动标签 / 转写 / 向量检索 | v2 文档 |
| Web/UI 主体 | **不自研通用文件管理 UI**,基于成熟开源底座 | [ADR-0001](../decisions/0001-no-full-custom-web-ui.md) |

## 2. 候选裁剪与重审历程

v0.1 → v0.2 → 重扫 → Phase B 收敛的 narrative,留给后续接手者理解决策来源:

| 阶段 | 主要事件 | 结果 |
| --- | --- | --- |
| v0.1 | 候选 C(NC + FastAPI 旁路,通过 SMB 外部存储) | 8 个候选裁剪到 3 个(A/B/C) |
| v0.2 | WebFetch 校验 NC SMB notify 限制(Linux Samba 不可靠) | C 修正为 C':NC datadirectory 直接放 ZFS dataset,绕开外部存储 |
| 候选重扫(4 强) | 引入 oCIS / ResourceSpace 作候选;Seafile 升档考虑 | NC / Seafile / oCIS / ResourceSpace 4 强对比 |
| Phase B 深入 | oCIS PosixFS 实验性确认 / Seafile blocks 非 POSIX + 无外部 webhook | v0.3:NC + oCIS(NFS) 首批 PoC;Seafile 备选;ResourceSpace 排除 |
| **v0.4 advisor 反馈 + Seafile pivot** | NC 视频体验弱是真问题;Seafile + **本地 MinIO 作 S3 backend** + MinIO bucket notification 是工程化可行的旁路通道;v0.3 把 Seafile 排除是基于"必须 inotify on POSIX"偏见 | **NC + Seafile(MinIO backend)首批 PoC**;oCIS 降级 P1 |
| **v0.5 用户决策 + PoC 实测** | NC 的 `oc_filecache` 膨胀(#7312)在 50-100 万文件量级是架构级风险,与本项目增长方向直接冲突;Seafile CE 实测**不支持 S3 backend**(`seaf-server` 无 s3 keyword),v0.4 §3.2 路线必须升 Pro 版;商业付费容忍度因核心架构必要性放开 | **Seafile (Pro) 单条 PoC**;NC 退出;详见 [ADR-0003](../decisions/0003-seafile-only-poc.md) |

### 2.1 当前候选状态(v0.5)

| 候选 | 状态 | 主要理由 |
| --- | --- | --- |
| **Seafile Pro + 本地 MinIO(S3 backend)** | ✅ **首批 PoC 唯一**(v0.5 收敛) | 块级同步快 2-3x;资源占用低;视频生态友好;commit object 是 atomic 信号(MinIO event 优于 inotify);**S3 backend 仅 Pro 提供**(CE 实测无 s3 code path,见 §6.3 F-X) |
| **Nextcloud (datadirectory)** | ❌ **v0.5 退出 PoC** | `oc_filecache` 膨胀(#7312)在 50-100 万文件量级是架构级问题,不是调优能解决;详见 [ADR-0003](../decisions/0003-seafile-only-poc.md) §6 与本节 §11 归档 |
| **oCIS + NFS backend** | 🟡 **维持 P1 长期** | 架构方向先进但大规模无公开案例;客户端兼容性未验证;若 Seafile Pro license 不可获取则 promote 到 P0 (见 ADR-0003 license 应急方案) |
| **oCIS + PosixFS** | ❌ 不进 PoC | 官方 2026 仍标 "experimental, not for production";无 stable 时间表 |
| **oCIS + S3 backend** | 🟡 P1 备选 | 若 P1 加 oCIS,优先用 S3 backend(可复用 Seafile 的 MinIO) |
| **Seafile CE(任何 backend)** | 🟡 P1 应急 | CE 不支持 S3 backend(实测 F-X);若必须用 CE 则只能 local fs,放弃 MinIO event 优势,inotify 回归 |
| **ResourceSpace** | ❌ 排除 | DAM 角色与 FastAPI 旁路重叠;无桌面客户端;无 100 TB+ 自建案例 |
| **全自研 FastAPI Web** | ❌ 排除 | [ADR-0001](../decisions/0001-no-full-custom-web-ui.md):文件管理要照顾的东西太多 |
| **SeaweedFS / JuiceFS / Ceph / MinIO + 自研 UI** | ❌ 排除 | 对象存储 / 大规模 FS 层,在已有"上层 + 旁路"思路下不增量;但 **MinIO 作 Seafile/oCIS 的 S3 backend** 是合理的(MinIO 不当主 UI) |
| **Filerun / 其他商业 MAM** | ❌ 排除 | 角色不匹配;Seafile Pro 由 v0.5 通过 ADR-0003 单独 unblock,纯开源约束放宽到"核心架构必要时商业 OK" |

## 3. 首批 PoC 主线

**v0.5 收敛后只有 Seafile 一条路线**。NC 路线分层(§3.1)保留作历史记录但已 frozen,不进 PoC;Seafile 路线(§3.2)是当前活跃方案。

### 3.1 NC 路线分层(v0.5 已归档 — 不进 PoC)

> ⚠️ **v0.5 归档说明**:本节描述的 NC 路线已退出首批 PoC,理由见 [ADR-0003](../decisions/0003-seafile-only-poc.md) §6 + 本文档 §11。
> 章节保留作参考(若 Seafile Pro 不可获取且 oCIS 也不通时的"已知不选 NC 的原因"快查);**不要按本节实施**。

```
┌────────────────────────────────────────────────────────────┐
│  Web/UX                                                    │
│    ├─ Nextcloud(浏览 / 上传 / 分享 / 权限 / 桌面客户端)    │
│    └─ FastAPI 自研页面(审批申请 / AI 检索 / 任务面板)     │
├────────────────────────────────────────────────────────────┤
│  业务服务(FastAPI + Celery)                               │
│    • 飞书 SSO / 审批对接 / open_id 映射(走 bridge)        │
│    • AI 索引 / 缩略图 / 转码(旁路任务)                   │
│    • 敏感目录下载代理 + 签名 URL                          │
│    • inotify watcher → 入消息队列                          │
├────────────────────────────────────────────────────────────┤
│  存储:TrueNAS Scale + ZFS                                  │
│    • dataset A = NC datadirectory(POSIX 直接挂载)        │
│    • dataset B = FastAPI 旁路输出(缩略图 / AI / 转码)     │
└────────────────────────────────────────────────────────────┘
```

NC `datadirectory = /srv/zfs/nc-data`(dataset A 挂载点);所有 NC 写入通过 PHP-FPM 走 POSIX。

### 3.2 Seafile Pro + 本地 MinIO(S3 backend)路线分层(v0.5 收敛)

> 🔑 **前提:Seafile Pro Edition**。2026-05-15 PoC 实测确认 CE 不带 S3 backend code path(详 §6.3 F-X)。Pro license 2026-05-16 接洽销售;[ADR-0003](../decisions/0003-seafile-only-poc.md) §"License / Pro 版前提" 列出 license 不可获取时的应急方案(oCIS 提前 / CE + local fs 接受 inotify 回归)。

#### 3.2.0 三个传统弱点的工程化应对(用户决策 2026-05-15)

| 弱点 | 传统印象 | 本项目应对 | 判定 |
| --- | --- | --- | --- |
| **无原生 webhook** | Seafile 不主动推送变更给第三方 | Seafile Pro 写 S3 → commit object PUT → MinIO bucket notification webhook → FastAPI;**事件延迟 +3s 被 AI 打标/转码自身耗时(几十秒至分钟)完全覆盖**;且 commit 是 atomic 信号(blocks/fs 全写完后才 PUT),比 NC inotify 减少"等文件写完"防御代码 | **不影响评审通过** |
| **无 POSIX 直读** | 外部进程拿不到完整文件 | **主动转码 → dataset B 代理版 → POSIX 直读** —— 上传时 FastAPI 旁路 seafdav 下载原片 → ffmpeg 转 720p H.264 代理版 → 写 dataset B;Web 播放/审批播放/AI pipeline 全部走 dataset B(POSIX 直读,零跳转);不做被动 cache(首播延迟、淘汰逻辑、AI 复用三处都赢) | **不影响评审通过** |
| **无 inotify 旁路** | 文件系统事件不可用 | MinIO bucket event 按 object key 前缀过滤(`commits/`)代替 inotify 路径过滤;**信号正确性反而优于 inotify**(无中途触发,无队列溢出丢事件) | **不影响评审通过** |

**主动转码代理版的容量预算**:10 万条短视频原片(50 TB)→ 代理版约 **2 TB**(~4%),完全可接受。

#### 3.2.1 分层架构

```
┌──────────────────────────────────────────────────────────────┐
│  Web/UX                                                       │
│    ├─ Seafile(浏览 / 上传 / 分享 / 桌面同步客户端)            │
│    │       (视频缩略图默认关掉,见 §6.3 P5 修订)             │
│    └─ FastAPI 自研页面(审批 / AI 检索 / 业务面板,与 NC 共享代码)│
├──────────────────────────────────────────────────────────────┤
│  业务服务(FastAPI + Celery,**与 NC 路线共享代码 80%+**)    │
│    └─ MinIO bucket notification → 事件入 Celery 队列          │
│       worker 调 Seafile REST API 拉 commit detail →           │
│       走 seafdav 下载完整文件 → 生成缩略图 / AI 标签           │
├──────────────────────────────────────────────────────────────┤
│  存储:本地 MinIO (S3 协议) + TrueNAS Scale + ZFS              │
│    • Seafile 配 S3 backend → MinIO 暴露 S3 API                │
│    • MinIO 数据物理写到 ZFS dataset A(POSIX 文件 on disk)    │
│    • dataset B 仍是 FastAPI 旁路输出(缩略图 / AI / 转码)      │
│    • ZFS 快照 / 备份 / 容量管理在 dataset A 上仍生效           │
└──────────────────────────────────────────────────────────────┘
```

**与 NC 路线的关键差异:**

| 维度 | NC 路线(§3.1) | Seafile 路线(本节) |
| --- | --- | --- |
| 旁路触发 | inotify on POSIX dir(1 步) | MinIO bucket event webhook(1 步) |
| 旁路读完整文件 | 直接读 POSIX 路径(0 额外步) | event → Seafile REST API 拉 commit detail(+1)→ seafdav WebDAV 下载(+1)= 2 额外步 |
| 总通信步数 | 1 | **3-4** |
| 数据真实落盘 | 直接成完整文件 in NC datadirectory | 分块为 ~8MB blocks 落 ZFS via MinIO S3 |
| FastAPI 反写约束 | 禁止写 NC datadir | 禁止写 Seafile 库(可写自己的 dataset B) |

**为什么 Seafile 4 步通信仍然 OK**:event-driven 仍优于轮询;每个 event 是 atomic commit 信号(不像 inotify 是文件级,可能在写入半途触发);Seafile commit log 是历史可重放的,丢 event 时能从最后一个 known commit 起重新追上。

> **降级到 P1 的 oCIS (NFS / S3) 路线分层** 在 v0.3 §3.2 历史版本中,本版省略 —— 因 oCIS 实际部署/兼容性未充分验证,等 NC + Seafile PoC 后再评估是否值得加跑。

### 3.3 共用数据流约束(NC + Seafile 通用)

| 方向 | 允许 | 机制 |
| --- | --- | --- |
| 底座 → FastAPI | ✅ | NC:inotify;Seafile:MinIO bucket event → Seafile REST + seafdav |
| FastAPI → 底座(写入数据目录) | 🟡 仅必要时 | **必须通过底座 API**(NC WebDAV / Seafile WebDAV);**禁止**直接写 NC datadirectory / Seafile blocks 目录 / MinIO bucket |
| 用户 → 底座 | ✅ | Web / 桌面客户端 / WebDAV |
| 用户 → FastAPI | ✅ | 自研页面(审批 / 检索) |

约束:**FastAPI 的输出文件放 dataset B,不进底座视图**,避免与底座的元数据 SoT 冲突。

### 3.4 底座 → FastAPI 旁路通道(分路线)

#### NC 路线:inotify 路径过滤(expert A 反馈)

FastAPI inotify watcher 必须忽略以下子路径,否则 NC 自己的写入会持续触发旁路:

| 路径模式 | 原因 |
| --- | --- |
| `appdata_<instanceid>/` | NC 预览缓存写入 |
| `<user>/files_trashbin/` | NC 回收站移动 |
| `<user>/files_versions/` | NC 文件版本 |

#### Seafile 路线:MinIO event 过滤

FastAPI 订阅 MinIO bucket notification(`s3:ObjectCreated:*`),按 object key 前缀过滤:

| 关注的对象 | 处理 |
| --- | --- |
| `commits/<repo_id>/<commit_id>` | **commit object 新增**:这是 Seafile "新版本就绪"的 atomic 信号,触发 FastAPI 拉 commit detail + 下载文件 |
| `blocks/...` | **block PUT**:忽略(单个 block 是文件碎片,不是完整内容信号) |
| `fs/...` | **fs object PUT**:忽略(目录树 metadata,commit 已 imply) |

Seafile 写入顺序保证 commit object 是**最后一个** PUT(所有 blocks + fs 写完才提 commit),所以监听 commit object event 等同于"完整新版本就绪"。这是 Seafile 设计的天然 sequencing 保障。

## 4. 敏感目录下载审批的挂载方式

3 种实现路径,**MVP 推荐 (b)**,与底座选型无关:

| 选项 | 描述 | 工作量 | UX |
| --- | --- | --- | --- |
| (a) 底座 Files Access Control + Webhook | 底座拦截下载 → 我方 webhook → 建飞书审批 → 回写底座 | 中(NC/oCIS app + Webhook) | 全程在底座 UI |
| **(b) 敏感目录关闭底座下载权限 + FastAPI 下载代理 + 签名 URL** | 用户在底座浏览,点下载跳到 FastAPI `/apply-download`,建审批,通过后签发临时签名 URL,FastAPI 流式返回 | **低**(自研下载代理) | 有跳转断点 |
| (c) 底座自定义 App | NC PHP App / oCIS extension 拦截下载 | 高 | 全程在底座 |

**审计断点风险(expert C 反馈):** 走 (b) 时底座 activity 日志看不到敏感下载;**审计 SoT 必须明确归 FastAPI 自己的日志/表**,且要和底座 activity 在用户口径上对齐。

## 5. 候选 4 强详细对比

> Phase B 调研收敛前的横向对比留档,供"为什么不选 X"回看。

| 维度 | Nextcloud | Seafile (CE) | oCIS 7 (NFS) | ResourceSpace |
| --- | --- | --- | --- | --- |
| **基础架构** | PHP-FPM + Postgres + Redis + cron | Go(seaf-server) + Python(seahub) + DB | Go 微服务 + xattr 元数据 | LAMP (PHP + MySQL) |
| **文件存储模型** | POSIX 直存 | **Git-like blocks**(非 POSIX) | 后端可选:NFS / S3 / PosixFS | POSIX 自管 |
| **外部进程 POSIX 直读** | ✅ | ❌ 必须走 API 或 seaf-fsck 导出 | ✅ NFS / PosixFS;S3 否 | ✅ |
| **外部 webhook 给第三方** | NC 有 webhooks app | **❌ 无原生**(社区诉求长期未满足) | gRPC + Events,可订阅 | webhook 插件,简单 |
| **inotify 旁路** | ✅ 原生 | ❌ blocks 模型不通 | ✅ NFS / PosixFS | ✅ |
| **视频缩略图** | FFmpeg 插件,体验弱 | thumbnail-server 13.0+ 独立,有 DoS 报告 | 待 PoC 验证 | DAM 专长(代理/关键帧) |
| **媒体元数据 schema** | 弱 / 自定义 tags | 弱 / 文件 tag | 元数据 xattr 灵活,需自建 schema | DAM 专长 |
| **大文件同步实测** | baseline | **2-3x 快** | 类 NC(WebDAV) | 不是同步系统 |
| **桌面/移动客户端** | ✅ 全平台成熟 | ✅ 全平台成熟 | 🟡 兼容 ownCloud 旧客户端,NC client 不保证 | ❌ 无桌面 |
| **资源消耗** | 4GB+ RAM | 1GB+ RAM | ~2GB+ RAM | 16GB+ RAM |
| **百人并发** | 调优后 100+ 临界 | 50-200+ 流畅 | 待 PoC | 偏低并发 |
| **元数据 bloat** | ⚠️ oc_filecache (#7312) | ✅ blocks 模型自然分布 | ✅ xattr 无 DB bloat | 🟡 MySQL 大表 |
| **大规模真实案例** | Telekom 7.2PB(联邦) | 清华百 TB | 无公开大规模案例 | < 70TB 量级 |
| **中文社区** | 良好 | ✅ 国人创立 | 弱 | 弱 |
| **OIDC / OAuth** | social_login app | 自带 generic OAuth2 | **默认 OIDC**,需 IdP | OAuth 插件 |
| **与飞书 SoT 集成难度** | 中 | 低 | 取决于 bridge 是否做 OIDC | 中 |

**净判断:** Phase B 把 Seafile / ResourceSpace / oCIS PosixFS+S3 都从首批 PoC 拿掉,理由见 §2.1。

## 6. PoC 验证发现(实施层)

### 6.1 来自 v0.2 一手证据(NC 侧)

| # | 发现 | 来源 |
| --- | --- | --- |
| 1 | NC SMB notify 在 Linux Samba 上 "**only reliable on Windows**" | NC Admin Manual,2026-05-15 |
| 2 | NC Local 外部存储无 inotify | NC 论坛 thread 140825 |
| 3 | `occ files:scan` 在大规模外部存储 20-50 file/s,100w 文件全扫 5-14h | NC issue #58549 + forum 907 |
| 4 | `oc_filecache` 表膨胀且不收缩,需定期 `pg_repack` | NC issue #7312 |
| 5 | 100+ 用户级需要 PG + Redis + APCu + NVMe + 16GB+ RAM | MassiveGRID 调优指南 |
| 6 | 100 用户级目录浏览延迟 ≈ 5s,桌面客户端冲突率上升 | MassiveGRID + NC 论坛 |

### 6.2 来自 storage-protocols-expert A-F 反馈(实施约束)

| # | 发现 | 影响 |
| --- | --- | --- |
| A | inotify 必须路径过滤 `appdata_<id>/` 和 `files_trashbin/` | 实施约束(见 §3.4) |
| B | ZFS dataset A 快照包含预览缓存 + 回收站,实际占用 > 100 TB | 容量规划 |
| C | 敏感下载走 FastAPI 代理后,底座 activity 看不到 → 审计 SoT 归 FastAPI 自己 | 合规/审计设计 |
| D | `oc_filecache` 不可旁路写入;业务字段必须放 FastAPI 自有 DB,用 fileid 外键 | 数据模型 |
| E | **预计撞墙顺序**:preview CPU → oc_filecache 膨胀 → 桌面同步 → WebDAV 吞吐 | PoC 测试焦点排序 |
| F | NC 默认全文搜索弱(LIKE on filename);AI 检索由 FastAPI 自研 | 边界明示 |

### 6.3 来自 Phase B 调研(候选重审)

| # | 发现 | 影响 |
| --- | --- | --- |
| P1 | oCIS PosixFS 在 2026-05 仍 experimental,无 stable 时间表 | PosixFS 不进 PoC |
| P2 | oCIS 默认 OIDC,严格要求 OIDC provider(Keycloak 或自实现) | 与飞书 SoT 集成路径设计 |
| P3 | Seafile 内置 notification-server 是 WebSocket 给 Seafile 客户端,**不**给第三方 webhook | **v0.4 修正:**用 Seafile S3 backend + MinIO bucket notification 提供 event-driven 旁路通道,见 §3.2;**非阻塞** |
| P4 | Seafile 文件存储是 Git-like ~8MB blocks,**非 POSIX** | **v0.4 接受:**走 MinIO event signal + Seafile REST commit detail + seafdav 完整文件下载(3-4 步通信),替代 inotify 单步模式;见 §3.2 |
| P5 | Seafile 内置视频缩略图启用后 DoS 风险(issue #2168) | **v0.4 修正:**Seafile 配置显式 `ENABLE_VIDEO_THUMBNAIL=False`,**FastAPI 旁路接管缩略图**(本就在 ADR-0001 规划范围内);**非阻塞** |
| P6 | ResourceSpace LAMP 架构 + 16GB+ 起 + 无桌面客户端 + < 70TB 案例 | 排除 |
| P7 (v0.4) | Seafile + MinIO event 的实际通信链路是 4 步(NC inotify 是 1 步) | 工程代价;**PoC 实测延迟**:用户上传 mp4 → FastAPI 拿到完整文件这段链路 P50 / P95 时间 |
| P8 (v0.4) | MinIO bucket notification 是工业级 webhook,但**Seafile commit 顺序写保证**(blocks 先 PUT,commit 对象最后 PUT)是设计上的天然 sequencing,无须我们额外协调 | 实施时验证此假设(看 Seafile 代码路径或实测) |
| **F-X (v0.5,KO 级)** | 2026-05-15 部署机 8.156.34.238 实测:`seafileltd/seafile-mc:latest` = 11.0.13,**`strings seaf-server \| grep -iE "s3\|aws\|amazon"` 完全无匹配**;写 `[block_backend] name = s3` 后上传文件,blocks 仍写入 local fs(`/shared/seafile/seafile-data/storage/`,6 个 commit/fs 对象),MinIO bucket 仍 0 对象;Seafile 官方 product 对比页确认"AWS S3/Ceph/阿里云后端"列在企业版独有 | **CE 不支持 S3 backend**,本路线必须升 Pro;触发 v0.5 收敛(ADR-0003) |
| F-1 (v0.5) | MySQL 8 默认 `caching_sha2_password` 与 seaf-server 内嵌 libmariadb 不兼容 → 衍生 admin 创建失败、system repo init 失败 | **docker-compose 用 MariaDB 10.11 LTS**,不要 MySQL 8;PoC scaffold 已修 |
| F-2 (v0.5) | `seafileltd/seafile-mc:13.0` tag 不存在(daocloud mirror 403) | latest = 11.0.13;Pro 用专属镜像 `seafileltd/seafile-pro-mc:<ver>` |
| F-3 (v0.5) | `seahub_settings.override.py` **不被 Seafile 自动 import**(`settings.py` 只 import `seahub_settings` 和 `local_settings`) | 挂载点改名 **`local_settings.py`**;否则 `ENABLE_VIDEO_THUMBNAIL=False` 等 PoC 配置静默失效 |
| F-4 (v0.5) | S3 backend conf 节名 — `[storage]` + `[s3]` **不被 seaf-server 识别** | 正确格式 `[block_backend]` + `[commit_object_backend]` + `[fs_object_backend]` 三节,每节填 `name = s3` + `bucket` + `key_id` + `key` + `host` + `use_v4_signature = true` + `path_style_request = true` + `use_https = false` |
| F-5 (v0.5) | seahub Python 端缺 `boto3` 时 Pro 版启动报 `ModuleNotFoundError` | image 内 `pip install boto3 botocore`;生产用自定义 Dockerfile pin 版本 |
| F-6 (v0.5) | 部署机 8.156.34.238 阿里云安全组开放 **22 / 80 / 443 / 6000-7000**;默认 8081/8083/9000/9001 不在范围 | PoC 端口搬 6000-7000;MinIO S3 API **不外暴露**(仅 docker network 内访问),Console 走 6901 |

## 7. 决策切换流程(v0.5)

```
前置:Seafile Pro license 是否落定(2026-05-16+ 接洽销售)
   ├─ 落定 ──→ 部署 PoC,跑 7 项验收(Issue #23)
   └─ 不可获取 ──→ 应急路径(见 ADR-0003):
                   1. oCIS + NFS 提前到 P0(Issue #13 升级)
                   2. Seafile CE + local fs(放弃 S3,接受 inotify 回归 + commit object 监听)
                   3. 联系其他商业替代(短期不推荐)

Seafile Pro PoC 跑通验收(7 项):
  1. 部署 — 库创建 / 上传 / 下载 / 同步
  2. 桌面同步客户端体验 — 剪辑师日常顺畅
  3. seafdav 下载性能 — <1GB 文件 localhost 秒级
  4. MinIO bucket notification 可达性 — commit event 推 FastAPI
  5. 全链路 — commit → event → seafdav 下载 → ffmpeg 转代理 端到端延迟
  6. 大量文件 Web UI 响应 — 10w 文件目录浏览不卡
  7. 异地同步 — Seafile 原生联邦 / rclone 补充可行性
   ↓
全过 → Seafile Pro + MinIO 路线最终确认,进入生产化阶段(硬件采购 + 部署 + 飞书集成联调)
有项不过 → 失败项归类:
   - 性能瓶颈 → 资源/参数调优(运维问题)
   - 信号正确性问题 → 设计回退到 commit log 轮询(降级,仍 Seafile)
   - 客户端兼容性 → 用 WebDAV 替代,客户端体验下降但可用
   - 全链路延迟过大 → 重审 ffmpeg/转码并发设置(不动 Seafile)
   - 全面不可接受 → 启动 oCIS + NFS PoC(Issue #13 promote)
```

## 8. NC 部署最小配置

```ini
# PHP-FPM
pm = static
pm.max_children = 50
pm.max_requests = 500
memory_limit = 512M
upload_max_filesize = 16G
post_max_size = 16G
max_execution_time = 3600

# OPcache
opcache.memory_consumption = 256
opcache.max_accelerated_files = 20000
opcache.interned_strings_buffer = 32
opcache.revalidate_freq = 60
opcache.jit = 1255
opcache.jit_buffer_size = 128M
```

```php
// config.php
'memcache.local' => '\OC\Memcache\APCu',
'memcache.distributed' => '\OC\Memcache\Redis',
'memcache.locking' => '\OC\Memcache\Redis',
'redis' => ['host' => '/var/run/redis/redis-server.sock', 'port' => 0],
'preview_max_x' => 2048,
'preview_max_y' => 2048,
'datadirectory' => '/srv/zfs/nc-data',
```

```ini
# PostgreSQL (16 GB server)
shared_buffers = 4GB
effective_cache_size = 12GB
work_mem = 64MB
maintenance_work_mem = 1GB
max_connections = 100
random_page_cost = 1.1
effective_io_concurrency = 200
```

```bash
# Cron
*/5 * * * * www-data php /var/www/nextcloud/cron.php
*/10 * * * * www-data php /var/www/nextcloud/occ preview:pre-generate
0 3 * * 0    postgres /usr/bin/pg_repack -d nextcloud -t oc_filecache
```

## 9. oCIS + NFS backend 部署最小配置(草案,待 PoC 校验)

```yaml
# docker-compose.yml 片段(草案,具体环境变量待 PoC 校验)
services:
  ocis:
    image: owncloud/ocis:7.0.1
    environment:
      OCIS_URL: https://ocis.internal
      OCIS_INSECURE: false
      OCIS_LOG_LEVEL: warning
      # Storage backend = decomposed posix(NFS 挂载点)
      OCIS_DECOMPOSEDFS_ROOT: /var/lib/ocis/storage/users
      # OIDC
      OCIS_OIDC_ISSUER: https://bridge.internal/oidc  # 由 bridge 提供
      WEB_OIDC_CLIENT_ID: ocis-web
    volumes:
      - nfs-mount:/var/lib/ocis/storage  # NFS export 自 TrueNAS
```

```bash
# TrueNAS Scale 上 NFS export(管理界面操作,记录 here)
# - export path: /mnt/tank/ocis-data
# - allowed network: <internal CIDR>
# - mapall root: yes(简化权限,生产环境讨论安全模型)
# - sync = standard
```

**待 PoC 实测的事项(§10 待办)**:
- oCIS decomposedfs 在 NFS 挂载下的元数据(xattr)是否完全工作 — NFSv4 要 enable xattr 支持
- NFS 客户端缓存策略对 oCIS 元数据一致性的影响
- oCIS 客户端兼容性:NC desktop client 能否连 oCIS

## 10. 待办

### 10.1 PoC 实测项(v0.5 单线)

> 详细验收标准 + 进度追踪在 **Issue #23 [PoC-Seafile]**。本节给文档化的执行清单。

**v0.5 部署阶段(已部分实测,2026-05-15 部署机 8.156.34.238):**

- [x] 部署机准备(8 核 / 14 GB / 2 TB NVMe / Ubuntu 22.04 / Docker 29.5.0)
- [x] PoC scaffold rsync 上去
- [x] MariaDB 10.11 替代 MySQL 8(F-1 修复)
- [x] `local_settings.py` 挂载(F-3 修复,**待 PoC scaffold 更新**)
- [x] 端口策略迁移 6000-7000(F-6 修复,**待 PoC scaffold 更新**)
- [ ] **拿到 Seafile Pro license + image** ← 阻塞,2026-05-16+ 联系销售
- [ ] 用 Pro image 重起,加 `[block_backend]/[commit_object_backend]/[fs_object_backend]` S3 配置(F-4 + F-X)
- [ ] 容器内 pip install boto3 botocore(F-5)
- [ ] 验证:上传 1 MB 文件后 MinIO bucket 有对象(KO criterion)

**Seafile Pro PoC 7 项验收(用户决策 §4):**

- [ ] V1: Seafile + 本地 MinIO(S3 backend)部署 — 能正常创建库、上传、下载、同步
- [ ] V2: 桌面同步客户端体验 — 剪辑师日常上传下载流程顺畅
- [ ] V3: seafdav 下载性能 — <1 GB 文件 localhost 下载耗时
- [ ] V4: MinIO bucket notification 可达性 — commit event 能否正常推送到 FastAPI
- [ ] V5: commit → event → seafdav 下载 → ffmpeg 转代理版 全链路端到端延迟可接受
- [ ] V6: 大量文件场景下 Web UI 响应 — 10 万文件级目录浏览不卡
- [ ] V7: 异地同步(Seafile 原生联邦 / rclone 补充)— 跨办公室同步可行性

**配套测试(与 7 项并行 / 后续):**

- [ ] FastAPI 旁路 MinIO event handler 在 50w 文件并发 PUT 下不丢事件、可靠重投
- [ ] Seafile commit object PUT 顺序保证(blocks 先 / commit 最后)— 看 Pro 代码路径或实测
- [ ] 主动转码代理版方案 e2e:ffmpeg → dataset B → Web 播放 — 验 50TB 原片 → ~2TB 代理版的容量假设
- [ ] 飞书 OAuth2 SSO 集成 e2e(Seafile Pro 自带 generic OAuth2 client + bridge OIDC,见 [feishu/decisions/0002](../../feishu/decisions/0002-bridge-as-oidc-provider.md));对应 Issue #24(feishu agent)
- [ ] 敏感目录"FastAPI 代理 + 签名 URL"e2e + 审计日志完整性
- [ ] 飞书 SoT JIT provisioning 流程
- [ ] 离职闭环:bridge 收到 `contact.user.deleted_v3` → Seafile API 禁号
- [ ] dataset B(FastAPI 输出区)隔离性:验证 FastAPI 写入不污染 Seafile 视图

### 10.2 调研/文档待办

- [ ] PoC 跑完后写 ADR-0003:文件管理底座选定(NC / oCIS / fallback)
- [ ] 容量规划文档(expert B 反馈):dataset A 实际占用 > 用户可见 100 TB,快照保留预留
- [ ] 审计 SoT 设计(expert C 反馈):FastAPI 日志/审计表 schema 与底座 activity 用户口径对齐
- [ ] 与方案 v2 §3 硬件清单对齐或修订(网络可放宽,见 §12)

## 11. 排除项归档(为什么不)

排除清单:

- **SeaweedFS / JuiceFS / Ceph**:对象存储 / 大规模 FS 层,在已有"上层 + 旁路"思路下不增量;Ceph 工程负担超百人公司可承受
- **MinIO 当用户主 UI**:Web/ACL/审计全自研,与 ADR-0001 冲突。**但 v0.4 把 MinIO 作 Seafile 的 S3 backend 是另一种用法,接受**(MinIO 不当用户 UI,只暴露 S3 协议 + bucket event 给 FastAPI;主 UI 是 Seafile)
- **商业 MAM / Seafile Pro / Filerun**:违反纯开源约束
- **Seafile Pro 的 webhook 扩展**:同上;v0.4 用 MinIO bucket event 替代
- **ResourceSpace** (Phase B):LAMP / 16GB+ / 无桌面 / < 70TB 量级,角色错位 + 重叠 FastAPI 旁路
- **PeerTube / Jellyfin / Plex**:视频流播 / UGC,与企业内部素材库错位
- **全自研 FastAPI Web UI**:[ADR-0001](../decisions/0001-no-full-custom-web-ui.md) 锁定

降级清单(v0.3 → v0.4 调整,**未排除**):

- **Seafile (本地存储 backend,非 S3)** [v0.3 → v0.4]:**降为 P1 fallback**;若 MinIO event 路径意外不顺,可退到 Seafile 默认本地 + 轮询 commit log
- **oCIS(NFS / PosixFS / S3 任一)** [v0.3 → v0.4]:**全部降级 P1**。理由:PosixFS experimental + NFS+xattr 兼容性未验证 + 客户端兼容性问号 + 中文社区弱;且 advisor 反馈 NC 视频弱后,把 PoC 算力 prioritized 给 Seafile pivot 更值;等 NC + Seafile PoC 后再评估是否值得加 oCIS

v0.5 调整(用户决策 + PoC 实测,详见 [ADR-0003](../decisions/0003-seafile-only-poc.md)):

- **Nextcloud (datadirectory)** [v0.4 → v0.5]:**退出首批 PoC,Issue #12 关闭**。理由:
  - `oc_filecache` 膨胀(#7312)是架构问题,不是调优能解决
  - 50-100 万文件量级下,NC 已知膨胀路径(preview CPU → oc_filecache → 桌面同步 → WebDAV 吞吐)与本项目数据增长方向直接冲突
  - NC 的 POSIX 直读 + inotify 友好优势,在本项目 async pipeline 场景下价值被稀释(主动转码代理版到 dataset B 已经覆盖 POSIX 直读需求)
  - Seafile 的块存储 + 原子 commit 在正确性上反而更优
  - NC 不是不能跑,而是"在错误的方向上花精力"——调优 DB、管理 oc_filecache、做 pg_repack 的时间应该花在业务开发上
- **Seafile CE(任何 backend)** [v0.4 → v0.5]:**降为 P1 应急**(原 v0.4 默认 CE,v0.5 实测 CE 无 S3 backend code path → 必须升 Pro)。CE only 适用于 Pro license 完全不可获取的应急路径,见 ADR-0003 §"License / Pro 版前提"
- **商业付费容忍度** [v0.4 → v0.5]:从"纯开源" → "**核心架构必要时商业 OK**"(Seafile Pro license 解锁 S3 backend);ADR-0003 落定该口径松动

## 12. 与方案 v2 的差异

| v2 方案 | 本调研 v0.5 |
| --- | --- |
| TrueNAS + ZFS + Nextcloud + FastAPI(隐含,通过 SMB 外部存储) | 修正为 **Seafile Pro + 本地 MinIO(S3 backend)**;**禁止 SMB 外部存储路径**;NC 路线已退出(详见 §11 + ADR-0003) |
| 仅 Nextcloud 一条路线 | **Seafile (Pro Edition) 单线 PoC**(v0.5 收敛);v2 未提 Seafile/MinIO/S3 backend |
| LDAP/AD 作用户身份源 | **已收敛为飞书通讯录 SoT**,LDAP/AD 砍掉,详见 [ADR-0002](../decisions/0002-feishu-contacts-as-identity-source.md) |
| 钉钉/企微 二选一 | **飞书**(2026-05-15 切换;企微 + 钉钉排除) |
| 4K ProRes / 剪辑挂载场景默认 | 短视频成片为主,**不挂载剪辑**;v2 存储吞吐 / 网络指标可放宽 |
| 25G + 万兆网络 | 不挂载剪辑后可放宽;具体硬件清单待 PoC 后修订 |
| 阶段一 AI 接入:云端 API + 自研 Python+Celery | 保留,与 FastAPI 旁路同栈;阶段二 RAG 算力位置待定 |
| 视频缩略图 / DAM 能力 | **主动转码 → dataset B 代理版**(720p H.264,~10-20 MB/min,占原片 ~4%);Web 播放/审批播放/AI pipeline 全走 dataset B POSIX 直读,零跳转;**不做被动 cache**(首播延迟、淘汰逻辑、AI 复用三处都赢) |
| 纯开源约束 [v0.5 调整] | "**核心架构必要时商业 OK**" — Seafile Pro license 解锁 S3 backend(对象存储后端是企业版独有功能);其他层维持开源(MinIO / ZFS / FastAPI / 飞书 bridge 等) |

## 13. 参考文档

| 标题 | URL | 抓取日期 |
| --- | --- | --- |
| NC SMB/CIFS Admin Manual | <https://docs.nextcloud.com/server/stable/admin_manual/configuration_files/external_storage/smb.html> | 2026-05-15 |
| NC Forum: Local external storage check for changes | <https://help.nextcloud.com/t/check-for-changes-option-for-local-external-storage/140825> | 2026-05-15 |
| NC Issue: oc_filecache excessively large | <https://github.com/nextcloud/server/issues/7312> | 2026-05-15 |
| NC Issue: S3 external storage 504 timeouts | <https://github.com/nextcloud/server/issues/58549> | 2026-05-15 |
| MassiveGRID: NC Performance Tuning Guide | <https://massivegrid.com/blog/nextcloud-performance-tuning-server-configuration-guide/> | 2026-05-15 |
| Seafile Data Model | <https://manual.seafile.com/latest/develop/data_model/> | 2026-05-15 |
| Seafile Notification Server | <https://manual.seafile.com/12.0/extension/notification-server/> | 2026-05-15 |
| Seafile Thumbnail Server | <https://manual.seafile.com/13.0/extension/thumbnail-server/> | 2026-05-15 |
| Seafile Forum: Trigger Webhook for Notifications(社区诉求) | <https://forum.seafile.com/t/trigger-webhook-for-notifications/12923> | 2026-05-15 |
| Sesame Disk: NC vs Seafile vs ownCloud | <https://sesamedisk.com/self-hosted-cloud-storage-nextcloud-seafile-owncloud/> | 2026-05-15 |
| oCIS Architecture | <https://doc.owncloud.com/ocis/next/admin/architecture/architecture.html> | 2026-05-15 |
| oCIS PosixFS(experimental) | <https://doc.owncloud.com/ocis/next/admin/deployment/storage/posixfs.html> | 2026-05-15 |
| oCIS Availability and Scalability | <https://doc.owncloud.com/ocis/next/admin/availability_scaling/availability_scaling.html> | 2026-05-15 |
| ownCloud Central: PosixFS stability thread | <https://central.owncloud.org/t/posixfs-stability/64761> | 2026-05-15 |
| ResourceSpace FAQ | <https://www.resourcespace.com/faq> | 2026-05-15 |
| Seafile setup_with_s3(S3 backend 官方文档) | <https://manual.seafile.com/latest/setup/setup_with_s3/> | 2026-05-15(v0.4 加) |
| Seafile Multiple Storage Backends | <https://manual.seafile.com/latest/setup/setup_with_multiple_storage_backends/> | 2026-05-15(v0.4 加) |
| MinIO bucket notification(webhook target) | <https://min.io/docs/minio/linux/administration/monitoring/bucket-notifications.html> | 2026-05-15(v0.4 加;实施时 fetch 校验最新版本) |
| Seafile data structure(blocks 模型理解) | <https://awant.medium.com/seafile-data-structure-c8a1e62a64e4> | 2026-05-15(v0.4 加) |
| Seafile 私有部署产品对比(CE vs Pro Edition 功能差异) | <https://www.seafile.com/product/private_server/> | 2026-05-15(v0.5 加;S3 backend / 文件锁 / 审计 / 服务器集群等列在 Pro 独有) |
| Seafile OAuth Authentication(CE/Pro 都支持的 OIDC 接入点) | <https://manual.seafile.com/latest/config/oauth/> | 2026-05-15(v0.5 加;feishu Issue #24 WP1 复用) |
