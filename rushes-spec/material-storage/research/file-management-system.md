# 调研:文件管理系统选型

> **调研日期:** 2026-05-15
> **版本:** v0.2(基于官方文档与社区一手证据校验后)
> **结论摘要:** 推荐 **候选 C'(修正版)**:TrueNAS Scale + ZFS + Nextcloud(内置 storage 模式,数据目录直接放 ZFS dataset)+ FastAPI 旁路(只读 + 自有写入域)。**坚决不走 SMB 外部存储**。下一分歧:NC 调优 PoC 跑过/不跑过决定退守候选 B。
> **状态:** 主对话推进中

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
| 审批通道 | **飞书 / Lark**(2026-05-15 由企微切换) | 用户口述 |
| AI 接入 | 阶段一含 自动标签 / 转写 / 向量检索 | v2 文档 |

## 2. 候选裁剪

| 候选 | 结论 | 主要理由 |
| --- | --- | --- |
| TrueNAS Scale + ZFS + Nextcloud | ✅ 候选 A | 单/双机即覆盖 100 TB;NC 提供成熟 Web/权限/分享/桌面客户端 |
| TrueNAS Scale + ZFS + 自研 FastAPI Web | ✅ 候选 B | UI 完全可控,深度集成顺手;UI 工作量翻倍 |
| **TrueNAS Scale + ZFS + Nextcloud(内置 storage)+ FastAPI 旁路** | ✅ **候选 C'(推荐)** | NC 干通用 UI,FastAPI 干企微/AI/审批代理;**关键修正:NC 数据目录直接放 ZFS dataset,不走 SMB 外部存储**(见 §9) |
| MinIO 单/双节点 + 自研 Web | 🟡 备选 | 对象存储语义可用;但 Web/ACL/审计全自研,在已有 ZFS+NC 路径下不增量 |
| Seafile | 🟡 备选 | 加密 + 同步好;视频浏览能力比 NC 弱,生态偏个人云 |
| SeaweedFS / JuiceFS | ❌ 排除 | 为海量小文件设计,百万文件以内属于过度工程 |
| Ceph(RGW / CephFS) | ❌ 排除 | 工程级解决方案,100 TB 用 Ceph 是过度 |
| 纯 NFS/SMB + 任意前端 | ❌ 排除 | 不是"文件管理系统",只是协议层 |
| 商业 MAM(iconik/CatDV/Mimir) | ❌ 排除 | 违反"纯开源"约束;且短视频场景下 MAM 的代理/时间码核心增值用不上 |

## 3. 推荐方向:候选 C'(修正后)

### 3.1 关键修正(基于 §9 验证)

v0.1 设想的"NC 通过 SMB 外部存储指向 ZFS"路径**不可行**:NC 的 SMB notify 在 Linux Samba 上"仅在 Windows SMB 服务器上可靠工作"(官方原文,见 §9);Local 外部存储无 inotify。这两条加起来意味着外部进程对存储的写入,NC 视图会有 15 分钟到数小时的滞后,且 cron 全扫描在 50-100w 文件级耗时不可接受(20-50 文件/秒 → 全扫 5-14 小时)。

**修正姿势:NC 把数据目录(`datadirectory`)直接配置到 ZFS dataset 上,以"内置 storage"形态运行**,从 NC 视角它没有外部存储,所有写入都通过 NC 自己的代码路径,`oc_filecache` 自然一致。

### 3.2 分层职责(修正后)

```
┌────────────────────────────────────────────────────────────┐
│  Web/UX 层                                                  │
│    ├─ Nextcloud(浏览 / 上传 / 分享 / 权限 / 审计 / 桌面客户端) │
│    └─ 自研 FastAPI 页面(审批申请 / AI 检索 / 任务面板)     │
├────────────────────────────────────────────────────────────┤
│  业务服务层(FastAPI + Celery)                              │
│    • 企微 OAuth / 审批对接 / userid 映射                    │
│    • AI 自动标签 / 转写 / 向量索引                          │
│    • 敏感目录下载代理 + 签名 URL 签发                       │
│    • 旁路索引器:inotify watch NC 数据目录 → 入消息队列     │
├────────────────────────────────────────────────────────────┤
│  存储:TrueNAS Scale + ZFS                                   │
│    • dataset A:NC datadirectory  ←── NC 唯一写入域         │
│    • dataset B:FastAPI 旁路输出(缩略图/AI 元数据/转码副本)│
│    • ZFS 快照(30/90/365)+ 异地对象存储冷备                │
└────────────────────────────────────────────────────────────┘
```

### 3.3 数据流约束(为避免双写冲突)

| 方向 | 允许 | 机制 |
| --- | --- | --- |
| NC → FastAPI | ✅ | FastAPI 用 inotify watch NC data dir,事件入队列,异步做缩略图/AI 索引,写到 dataset B |
| FastAPI → NC(写文件到 NC 视图) | 🟡 仅在必要时 | 必须通过 NC WebDAV API 写入,**禁止**直接 POSIX 写 NC datadir(否则 NC 看不到) |
| 用户 → NC(浏览/上传/下载) | ✅ | NC Web UI / 桌面客户端 / WebDAV |
| 用户 → FastAPI(审批/AI 检索) | ✅ | FastAPI 自研页面 |

约束:**FastAPI 的输出文件放 dataset B,不进 NC 视图**。NC 是用户素材的唯一写入门户。

## 4. 敏感目录下载审批的挂载方式

| 选项 | 描述 | 工作量 | UX |
| --- | --- | --- | --- |
| (a) NC Files Access Control + Webhook | NC 拦截下载 → 触发 webhook → 我方建企微审批 → 回写 NC 放行/拒绝 | 中 | 全程在 NC 内 |
| **(b) 敏感目录 NC 关闭下载权限 + FastAPI 下载代理 + 签名 URL** | 用户在 NC 浏览但点下载跳转到我方 `/apply-download`,我方建审批,通过后签发临时签名 URL 走 FastAPI 流式返回 | **低** | 有跳转断点 |
| (c) 自定义 NC PHP App | 写 NC App 拦截下载请求 | 高 | 全程在 NC 内 |

**MVP 推荐 (b)**:实现成本最低,且天然规避 NC PHP 生态;边界清晰(NC 管文件,FastAPI 管业务)。后期如体验断点严重再升级到 (a)。

## 5. 候选 A / B / C' 的实质性分歧

- **A**(NC 主 UI,无旁路):无 FastAPI 旁路 → 企微审批/AI 都得做成 NC App(PHP),工作量与生态学习成本上升;短视频场景的视频特有处理(代理生成 / AI 标签)NC 原生支持薄弱
- **B**(全自研,无 NC):需要从零写"上传/浏览/分享/权限/审计/桌面同步" → 至少 6-9 人月,且桌面客户端基本得砍掉
- **C'**(NC + FastAPI 旁路,本文推荐):NC 干通用 UI,FastAPI 干业务专属;工作量最小、风险分散;关键风险是 NC 在 50-100w 文件下的运维压力(见 §9)

## 6. 待办(更新)

- [ ] **PoC 实测项目**(见 §9):
  - [ ] NC 内置 storage 在 50w / 100w 模拟文件下的目录浏览/搜索延迟
  - [ ] NC `preview:generate-all` 在 50w 短视频文件下的耗时(社区数据:4 核 8-12 小时,需校验)
  - [ ] 桌面客户端在 100 用户级的 `oc_filecache` 增长曲线 + 同步冲突频率
- [ ] **NC 服务端最小调优配置**(已基于社区清单备好,见 §11)
- [ ] 一旦 PoC 通过,写 ADR:`decisions/0001-file-management-stack.md`
- [ ] **决策切换条件**(见 §10):明确什么 PoC 结果会让我们从 C' 退到 B

## 7. 排除项归档(为什么不)

- **SeaweedFS / JuiceFS**:为海量小文件 / POSIX-on-对象存储 设计,百万文件以内属于过度工程
- **Ceph**:工程级解决方案,100 TB 规模负担超过百人公司可承受运维
- **MinIO**:可做,但 Web / 权限 / 审计 全自研;在已有 ZFS+NC 路径下不增量
- **商业 MAM**:违反纯开源约束;且短视频场景下代理/时间码增值用不上
- **Seafile**:Web 端视频浏览能力弱于 NC

## 8. 与方案 v2 的差异

| v2 方案 | 本调研 v0.2 | 备注 |
| --- | --- | --- |
| TrueNAS + ZFS + Nextcloud + FastAPI(隐含,通过 SMB) | 同 = 候选 C',但**禁止 SMB 外部存储路径** | v2 隐含的 SMB 路径在 Linux Samba 上 notify 不可靠,见 §9 |
| LDAP/AD 作为用户身份源 | **未冻结**(下一项调研) | 见 [`../README.md`](../README.md) Q2 |
| 钉钉/企微 二选一 | **飞书**(2026-05-15 由企微切换;v2 未列飞书) | 见 [`./feishu-approval.md`](./feishu-approval.md)(待建) |
| 4K ProRes / 剪辑挂载场景默认 | **短视频成片为主,不挂载剪辑** | v2 存储吞吐/网络指标可放宽 |

## 9. PoC 验证发现(基于一手证据)

### 9.1 SMB notify 在 Linux Samba 上不可靠

**官方原文**(Nextcloud Admin Manual, SMB/CIFS):
> Due to limitations of linux based SMB servers, this feature only works reliably on Windows SMB servers.

来源:<https://docs.nextcloud.com/server/stable/admin_manual/configuration_files/external_storage/smb.html>,抓取于 2026-05-15

**影响:** v2 方案隐含的"NC 通过 SMB 外部存储指向 TrueNAS"路径会有以下问题:
- 外部进程(包括 FastAPI 旁路、ZFS 直接挂载剪辑师机)写入 NC 看不到
- Fallback `occ files:scan --unscanned --all` 默认随 NC cron(15 分钟一次)
- 大规模扫描代价 见 §9.3

### 9.2 Local 外部存储无 inotify

NC 的 "Local" 外部存储(指向本地 POSIX 路径)同样缺乏自动变更检测机制;"Check for changes" 选项被社区评价为"不完善的变通方案"。

来源:<https://help.nextcloud.com/t/check-for-changes-option-for-local-external-storage/140825>,抓取于 2026-05-15

**结论:** 任何"NC 通过外部存储指向 ZFS 路径,让外部进程写入"的设计都有持续元数据滞后问题。唯一干净的方案是 NC 内置 storage 模式(NC datadirectory 直接放 ZFS dataset 上,所有 NC 视图内写入走 NC 自己的代码路径)。

### 9.3 `occ files:scan` 性能基线

| 来源 | 场景 | 数据 |
| --- | --- | --- |
| Issue #58549 | S3 外部存储,数百万对象 | 20-50 文件/秒,且会 timeout |
| Forum thread 907 | NC 10 beta,3-6w 本地文件 | 4-10 分钟 |
| 派生估算 | 100w 文件 × 20-50 files/s | 5-14 小时全扫,**单次不可接受** |

来源:
- <https://github.com/nextcloud/server/issues/58549>(标题:`occ files:scan and Web UI fail with 504 Timeouts when indexing massive S3 External Storage buckets`)
- <https://help.nextcloud.com/t/external-storage-performance-occ-files-scan-all/907>

**优化手段**(社区共识):
- 用 `targeted scan`(指定 path)而非 `--all`
- 数据库锁 → Redis 锁(`memcache.locking = '\OC\Memcache\Redis'`)
- SMB 场景下用 `php-smbclient`(PHP 扩展)而非 `smbclient` 二进制
- 升级 PostgreSQL(优于 MySQL 在 oc_filecache 大表 join 场景)

### 9.4 `oc_filecache` 表膨胀

NC issue #7312 长期开放:"File cache table excessively large (and does not shrink after data removal)"。意味着百万级文件 + 频繁增删的场景下,DB 表会持续膨胀且 VACUUM 不释放空间。

来源:<https://github.com/nextcloud/server/issues/7312>,抓取于 2026-05-15

**缓解:** 定期 `VACUUM FULL` + Postgres `pg_repack`(在线表重组);需要数据库层运维投入。

### 9.5 100+ 用户级 NC 服务端调优清单(社区落地数据)

来源:MassiveGRID 《Nextcloud Performance Tuning Guide》,<https://massivegrid.com/blog/nextcloud-performance-tuning-server-configuration-guide/>,抓取于 2026-05-15

**最低硬件:**
- 内存 ≥ 16 GB
- CPU ≥ 4 核(且 `/proc/stat` steal < 5%)
- 存储 = NVMe(SATA SSD 不够),延迟 < 10ms,利用率 < 90%

**软件栈必备:**
- 数据库 = **PostgreSQL**(不是 MySQL)
- 锁 = **Redis**(memcache.locking)
- 本地 cache = APCu
- PHP-FPM `pm = static`,`max_children ≈ 50`(16GB 服务器)
- OPcache `memory_consumption = 256MB`,`max_accelerated_files = 20000`

**预览生成:** `preview:generate-all` 在 4 核上耗时**8-12 小时**(初始全量),之后 cron `preview:pre-generate` 每 10 分钟增量

**预览限制(降低空间占用):**
```php
'preview_max_x' => 2048,
'preview_max_y' => 2048,
```

### 9.6 桌面客户端在 100+ 用户级的痛点

社区报告(MassiveGRID + NC 论坛):
- 文件浏览器目录加载延迟 ≈ 5 秒(未调优时)
- 大量上传会卡 100 文件一批(Windows 客户端)
- 桌面/移动同步冲突频率显著上升

**结论:** 桌面客户端给 100 人全员开,需要严肃运维(NC server 调优 + 监控 + 用户培训)。如果只给核心剪辑/运营开桌面客户端,普通员工用 Web UI 浏览,运维压力会大幅下降。

## 10. 决策切换条件:何时从 C' 退到 B

如果 PoC 触发以下任一条件,**推荐放弃候选 C',改走候选 B(全自研 FastAPI Web)**:

1. NC 在 50w 模拟文件下目录加载 > 3 秒,且按 §9.5 调优后仍不达标
2. `preview:generate-all` 在 50w 短视频上耗时 > 24 小时(对短视频内容工厂效率不可接受)
3. `oc_filecache` 在 1 个月模拟负载下膨胀 > 表数据 3 倍,且 VACUUM 不收敛
4. 桌面客户端在 30+ 模拟用户同步同一项目时冲突率 > 5%

**候选 B 的预期工作量:** UI 自研 6-9 人月(FastAPI + Vue/React + WebDAV-like 文件接口 + 缩略图/预览 + 分享/权限模型 + 审计 + 桌面客户端 可选)。比 C' 的 2-3 人月翻 2-3 倍,但绕过 NC 自身瓶颈,且企微/AI 集成完全顺手。

## 11. 如果走 C',NC 部署最小可行配置(直接照抄)

> 这一节供 PoC 阶段直接落地。

```ini
# PHP-FPM (/etc/php/8.x/fpm/pool.d/nc.conf)
pm = static
pm.max_children = 50
pm.max_requests = 500
memory_limit = 512M
upload_max_filesize = 16G
post_max_size = 16G
max_execution_time = 3600
```

```ini
# OPcache
opcache.memory_consumption = 256
opcache.max_accelerated_files = 20000
opcache.interned_strings_buffer = 32
opcache.revalidate_freq = 60
opcache.jit = 1255
opcache.jit_buffer_size = 128M
```

```php
// NC config.php
'memcache.local' => '\OC\Memcache\APCu',
'memcache.distributed' => '\OC\Memcache\Redis',
'memcache.locking' => '\OC\Memcache\Redis',
'redis' => [
    'host' => '/var/run/redis/redis-server.sock',
    'port' => 0,
],
'preview_max_x' => 2048,
'preview_max_y' => 2048,
'datadirectory' => '/srv/zfs/nc-data',  // ← ZFS dataset 挂载点
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

## 参考文档清单

| 文档 | URL | 抓取日期 |
| --- | --- | --- |
| NC SMB/CIFS Admin Manual | <https://docs.nextcloud.com/server/stable/admin_manual/configuration_files/external_storage/smb.html> | 2026-05-15 |
| NC Forum: Local external storage check for changes | <https://help.nextcloud.com/t/check-for-changes-option-for-local-external-storage/140825> | 2026-05-15 |
| NC Forum: External Storage Performance occ files:scan | <https://help.nextcloud.com/t/external-storage-performance-occ-files-scan-all/907> | 2026-05-15 |
| NC Issue: oc_filecache excessively large | <https://github.com/nextcloud/server/issues/7312> | 2026-05-15 |
| NC Issue: S3 external storage 504 timeouts | <https://github.com/nextcloud/server/issues/58549> | 2026-05-15 |
| MassiveGRID: NC Performance Tuning Guide | <https://massivegrid.com/blog/nextcloud-performance-tuning-server-configuration-guide/> | 2026-05-15 |
