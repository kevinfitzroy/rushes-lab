# 调研:文件管理系统选型

> **调研日期:** 2026-05-15
> **版本:** v0.3(基于 expert agent 反馈 + 候选重扫 + Phase B 深入调研)
> **结论摘要:** 首批 PoC = **Nextcloud (datadirectory 模式) + oCIS (NFS backend) 二者**。两者底层都是 POSIX 友好,FastAPI inotify 单向读旁路通用。Seafile / oCIS+PosixFS / oCIS+S3 留作 fallback,不进首批 PoC。
> **状态:** 主对话推进中,首批 PoC 进入计划阶段

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
| Phase B 深入 | oCIS PosixFS 实验性确认 / Seafile blocks 非 POSIX + 无外部 webhook | 收敛到 NC + oCIS(NFS) 二者首批 PoC;Seafile 备选;ResourceSpace 排除;PosixFS 不进 PoC |

### 2.1 当前候选状态

| 候选 | 状态 | 主要理由 |
| --- | --- | --- |
| **Nextcloud (datadirectory)** | ✅ **首批 PoC** | POSIX 直存,inotify 友好;生态完整;运维负担与 bloat 已知 |
| **oCIS + NFS backend** | ✅ **首批 PoC** | NFS POSIX 语义,inotify 工作;Go 微服务 + xattr 元数据避 PG bloat;NFS export 在 TrueNAS 零成本 |
| **oCIS + PosixFS** | ❌ 不进 PoC | 官方 2026 仍标 "experimental, not for production";无 stable 时间表 |
| **oCIS + S3 backend** | 🟡 fallback | 旁路要改 S3 API 模式;偏离 ZFS 本地设计 |
| **Seafile (CE)** | 🟡 fallback | blocks 非 POSIX + 无外部 webhook,旁路 work-around 复杂;同步性能优势抵不上 |
| **ResourceSpace** | ❌ 排除 | DAM 角色与 FastAPI 旁路重叠;无桌面客户端;无 100 TB+ 自建案例 |
| **全自研 FastAPI Web** | ❌ 排除 | [ADR-0001](../decisions/0001-no-full-custom-web-ui.md):文件管理要照顾的东西太多 |
| **SeaweedFS / JuiceFS / Ceph / MinIO + 自研** | ❌ 排除 | 对象存储 / 大规模 FS 层,在已有"上层 + 旁路"思路下不增量(v0.2 §7) |
| **商业 MAM / Seafile Pro / Filerun** | ❌ 排除 | 违反纯开源约束 |

## 3. 首批 PoC 主线

两条路线**共享 FastAPI 旁路设计**,只换底座。这是选 NC vs oCIS 二者 PoC 的关键工程价值:**只测底座差异,不重写旁路**。

### 3.1 NC 路线分层

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

### 3.2 oCIS (NFS backend) 路线分层

```
┌────────────────────────────────────────────────────────────┐
│  Web/UX                                                    │
│    ├─ oCIS(浏览 / 上传 / 分享 / 客户端;严格 OIDC)        │
│    └─ FastAPI 自研页面(同上)                            │
├────────────────────────────────────────────────────────────┤
│  业务服务(FastAPI + Celery,与 NC 路线相同)             │
├────────────────────────────────────────────────────────────┤
│  存储:TrueNAS Scale + ZFS + NFS export                     │
│    • dataset A → 通过 NFSv4 export 给 oCIS 节点挂载       │
│    • dataset B = FastAPI 旁路输出(本地直读)              │
└────────────────────────────────────────────────────────────┘
```

oCIS 把 dataset A 当作 NFS 远程挂载,oCIS 内部 storage provider 在 NFS 上读写 + 维护 xattr 元数据。FastAPI 通过 ZFS 本机 POSIX 路径(或同一 NFS 挂载)inotify watch。

### 3.3 共用数据流约束(两路线都成立)

| 方向 | 允许 | 机制 |
| --- | --- | --- |
| 底座 → FastAPI | ✅ | inotify watch dataset A,事件入队,异步处理 |
| FastAPI → 底座(写入数据目录) | 🟡 仅必要时 | **必须通过底座 API**(NC WebDAV / oCIS WebDAV);**禁止**直接 POSIX 写 |
| 用户 → 底座 | ✅ | Web / 桌面客户端 / WebDAV |
| 用户 → FastAPI | ✅ | 自研页面(审批 / 检索) |

约束:**FastAPI 的输出文件放 dataset B,不进底座视图**,避免与底座的元数据 SoT 冲突。

### 3.4 inotify 路径过滤(expert A 反馈,实施约束)

FastAPI inotify watcher 必须忽略以下子路径,否则底座自己的写入会持续触发旁路:

| 底座 | 必须忽略的路径 |
| --- | --- |
| NC | `appdata_<instanceid>/`(预览缓存)、`<user>/files_trashbin/`(回收站)、`<user>/files_versions/`(版本) |
| oCIS | `.oc-nodes/`(metadata 区,xattr 之外的辅助文件)、`uploads/`(分块上传中间区,**待 PoC 校验**) |

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
| P3 | Seafile 的 notification-server 是 WebSocket 给客户端,**不**支持外部 webhook | Seafile 旁路接入硬约束 |
| P4 | Seafile 文件存储是 Git-like blocks,**非 POSIX** | inotify 单向读模式不适用 |
| P5 | Seafile 视频缩略图启用后有 DoS 报告(issue #2168) | 谨慎启用 |
| P6 | ResourceSpace LAMP 架构 + 16GB+ 起 + 无桌面客户端 + < 70TB 案例 | 排除 |

## 7. 决策切换流程

```
首批 PoC (NC + oCIS NFS) 开跑
   ↓
判定 NC 是否过关:
  - preview:generate-all 50w 短视频 < 24h?
  - 桌面客户端 30+ 用户并发同步冲突率 < 5%?
  - oc_filecache 1 月模拟负载下 VACUUM 收敛?
  - 目录加载 P95 < 3s?
   ↓
判定 oCIS NFS 是否过关:
  - 同等场景指标 + 客户端兼容性(ownCloud/NC desktop 接 oCIS)
  - NFS 层稳定性 + xattr 元数据机制实测
   ↓
两个都过 → 商业/运维维度二选一(写 ADR-0003)
NC 过 oCIS 不过 → NC
oCIS 过 NC 不过 → oCIS(注意 NC 客户端可能不兼容 oCIS,要做迁移成本评估)
两者都不过 → fallback 顺序:
   1. Seafile(接受 work-around 工程量,见 §2.1)
   2. oCIS + S3 backend(改对象存储模式)
   3. 重新审视架构(可能需要回到全自研讨论,但 ADR-0001 锁死了这条路 — 需用户重新决策)
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

### 10.1 PoC 实测项(首批)

**NC 路线:**

- [ ] 50w / 100w 模拟视频文件(空填充 + 随机名,< 1GB)灌入 datadirectory,跑:
  - 目录浏览延迟 P50/P95
  - `files:scan --all` 全扫耗时
  - `preview:generate-all` 耗时(focus,expert E 撞墙顺序首位)
  - `oc_filecache` 大小增长 + `pg_repack` 后收敛情况
- [ ] 30+ 模拟用户并发桌面客户端同步同一项目目录的冲突率
- [ ] FastAPI inotify watcher + 路径过滤(§3.4)在 50w 文件下的事件吞吐
- [ ] 敏感目录"FastAPI 代理 + 签名 URL"方案 e2e 测试 + 审计日志完整性

**oCIS 路线:**

- [ ] 同等数据量在 NFS-mounted decomposedfs 下的目录浏览 / 上传 / 缩略图生成耗时
- [ ] oCIS xattr 元数据机制实测(在 NFS 挂载下是否完全可用)
- [ ] 客户端兼容性:NC desktop / ownCloud desktop / 移动客户端
- [ ] 与 bridge 的 OIDC 集成 e2e 测试(配合 MS-FB-004 SSO 契约)

**共享测试:**

- [ ] FastAPI 旁路在底座切换下的"零代码改动"验证
- [ ] 飞书 SoT JIT provisioning 流程(底座侧用户态建账号)
- [ ] 离职闭环:bridge 收到 `contact.user.deleted_v3` → 底座 API 禁号

### 10.2 调研/文档待办

- [ ] PoC 跑完后写 ADR-0003:文件管理底座选定(NC / oCIS / fallback)
- [ ] 容量规划文档(expert B 反馈):dataset A 实际占用 > 用户可见 100 TB,快照保留预留
- [ ] 审计 SoT 设计(expert C 反馈):FastAPI 日志/审计表 schema 与底座 activity 用户口径对齐
- [ ] 与方案 v2 §3 硬件清单对齐或修订(网络可放宽,见 §12)

## 11. 排除项归档(为什么不)

- **SeaweedFS / JuiceFS / Ceph**:对象存储 / 大规模 FS 层,在已有"上层 + 旁路"思路下不增量;Ceph 工程负担超百人公司可承受
- **MinIO**:对象存储,Web/ACL/审计全自研,且与 ADR-0001 冲突(不自研 UI)
- **商业 MAM / Seafile Pro / Filerun**:违反纯开源约束
- **Seafile Pro 的 webhook 扩展**:同上
- **ResourceSpace** (Phase B):LAMP / 16GB+ / 无桌面 / < 70TB 量级,角色错位 + 重叠 FastAPI 旁路
- **PeerTube / Jellyfin / Plex**:视频流播 / UGC,与企业内部素材库错位
- **全自研 FastAPI Web UI**:[ADR-0001](../decisions/0001-no-full-custom-web-ui.md) 锁定

## 12. 与方案 v2 的差异

| v2 方案 | 本调研 v0.3 |
| --- | --- |
| TrueNAS + ZFS + Nextcloud + FastAPI(隐含,通过 SMB 外部存储) | 修正为 NC datadirectory + FastAPI 旁路(直接 POSIX);**禁止 SMB 外部存储路径** |
| 仅 Nextcloud 一条路线 | **PoC 二选一**:NC + oCIS(NFS),后者是 v2 未提的现代候选 |
| LDAP/AD 作用户身份源 | **已收敛为飞书通讯录 SoT**,LDAP/AD 砍掉,详见 [ADR-0002](../decisions/0002-feishu-contacts-as-identity-source.md) |
| 钉钉/企微 二选一 | **飞书**(2026-05-15 切换;企微 + 钉钉排除) |
| 4K ProRes / 剪辑挂载场景默认 | 短视频成片为主,**不挂载剪辑**;v2 存储吞吐 / 网络指标可放宽 |
| 25G + 万兆网络 | 不挂载剪辑后可放宽;具体硬件清单待 PoC 后修订 |
| 阶段一 AI 接入:云端 API + 自研 Python+Celery | 保留,与 FastAPI 旁路同栈;阶段二 RAG 算力位置待定 |

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
