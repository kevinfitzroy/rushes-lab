# ADR-0005 — 去除 Seafile 中间层,采纳 MinIO + 自研业务 UI 极简架构

- Status: **accepted**(2026-05-16,§7 全 verify 通过 + Phase A.2 PoC 完整跑通 + 业务侧产品决策 §7-bis 落地)
- Date: 2026-05-16
- ⚠️ **2026-05-16 底座选型纪要**(详 §10):MinIO 公司 2026-04-25 archive 了开源仓库,推闭源 AIStor。经候选评估(SeaweedFS / RustFS / Garage / AIStor / 公有云),**底座选型收敛至 [Pigsty MinIO fork](https://github.com/pgsty/minio)**(AGPLv3,自 archived 前的 `minio/minio` 社区 fork)。链路与飞书集成接缝详 §11。
- Supersedes(部分推翻): [ADR-0003 — PoC 收敛到 Seafile only(需 Pro Edition)](./0003-seafile-only-poc.md)
- Amends: [ADR-0001 — 不自研通用 Web UI](./0001-no-full-custom-web-ui.md)(自研业务 UI 范围扩大)
- Related:
  - [ADR-0002 — 飞书通讯录作身份源](./0002-feishu-contacts-as-identity-source.md)(不受影响,继续生效)
  - [feishu/decisions/0002-bridge-as-oidc-provider.md](../../feishu/decisions/0002-bridge-as-oidc-provider.md)(不受影响)
  - [file-management-system.md v0.5](../research/file-management-system.md)(需重写 §3 收敛后架构)
  - [audit-schema.md v1](../audit-schema.md)(PR #30 需修订,见 §8)
  - feishu/contracts/sso-seafile.md(MS-FB-006)/ approval-seafile.md(MS-FB-007)— 见 §8

---

## 决策结论

**去除 Seafile 中间层,采纳三层极简架构:**

```
┌──────────────────────────────────────────────┐
│  material-storage 业务 UI(自研,Vue/React)    │
└──────────────────────────────────────────────┘
                    ↓
┌──────────────────────────────────────────────┐
│  material-storage 业务后端(FastAPI)           │
│   + audit / 飞书 / 旁路 worker / 权限 / 审批    │
└──────────────────────────────────────────────┘
                    ↓ S3 协议
┌──────────────────────────────────────────────┐
│  MinIO(对象存储,Apache 2.0 兼容生态)          │
│  + bucket notification 触发旁路 worker         │
└──────────────────────────────────────────────┘
                    ↓
┌──────────────────────────────────────────────┐
│  ZFS dataset(本地)+ MinIO replication(异地)  │
└──────────────────────────────────────────────┘
```

**Seafile(无论 CE 还是 Pro)从架构中移除**。原 ADR-0003 假设 "Seafile Pro 作存储 + 同步 + 协作中间层" 的前提在业务场景重审后**不再成立**。

---

## 1. 触发本次重审的四个业务诉求确认(2026-05-16 对话纪要)

业务侧对 v0.5 架构的四个根本性追问,逐条拆解 Seafile 杀手锏的实际价值:

### 1.1 业务资源类型 = 视频 / 图片 → Block-level 增量同步价值近零

| 文件类型 | 工作模式 | 增量同步红利 |
| --- | --- | --- |
| 摄像机原片(.mov / .mp4 / .braw) | 拍完整段上传,**永远不改** | ❌ |
| RAW 照片 / JPG / PNG | 上传后不可变,导出是新文件 | ❌ |
| 剪辑工程文件(.prproj / .fcpx) | 保存即整文件重写;文件本身 MB 级 | ❌ |
| Photoshop / Illustrator(.psd / .ai) | 保存即整文件重写 | ❌ |
| 导出成片 | 每次导出 = 新文件名 | ❌ |

→ Seafile **block-level 增量同步**(基于 CDC content-defined chunking)是为"个人 Documents / 代码 / 邮件归档 / 大型数据库镜像"场景设计的,**与视频 / 图片业务不对口**。

### 1.2 工作模式 = 申请 → 审批 → 显式下载 / 上传 → 挂载盘价值为零

业务侧实际工作模式:

> 员工接触到的只是很少一部分资源 → 申请文件夹权限 → 主管审批 → 下载 → 上传新文件

挂载盘(seadrive / NextCloud 桌面 / Dropbox Smart Sync)的设计前提是 "**用户能浏览整个共享空间,本地像访问自己硬盘**",适合**共享办公盘**模式(全员见全部)。

本业务是**审批驱动 + 显式取放**模式,与挂载盘体验直接冲突:
- 员工**不应该**看到全部目录树(权限隔离)
- 是申请后才能拿文件,不是"自己浏览"
- 取到后通常是上传新文件,不是原地修改
- Web UI 上传 / 下载已经满足

→ Seafile 桌面同步客户端 / 挂载盘 / 移动 app 对本业务**均不构成价值**。

### 1.3 NC / Seafile 在 MinIO 之上的边际价值与业务模型重复

把"纯 MinIO + 自研业务 UI" 与 "MinIO + NC/Seafile + 自研业务 UI" 逐项对照:

| 需求 | 纯 MinIO + 自研 | + NC/Seafile | 边际价值 |
| --- | --- | --- | --- |
| 对象存储 | ✅ MinIO | (同) | 0 |
| Web 业务 UI | 自研(本就要做) | 通用 UI + 业务 UI 双轨 | **负**(维护两套) |
| 子目录权限 | 飞书审批 + FastAPI 代理(模型 B,已决) | NC 原生 / Seafile Pro | **重复** |
| 审计日志 | 自建 audit 表(PR #30) | NC/Seafile 自带,但字段不符业务 | **重复** |
| 全文检索 | 业务元数据自建(更精准) | NC ES app,**对二进制视频意义有限** | 接近 0 |
| 共享链接 | 走飞书审批通道 | 原生 share link | **重复** |
| 用户 / 组管理 | 飞书 SoT + material-storage user 表 | NC/Seafile 自带 | **重复**(与 ADR-0002 冲突) |
| 旁路 worker(转码 / AI) | FastAPI + MinIO event | 无关 | 0 |
| 预览生成(缩略图 / 抽帧) | 自建(本就要做) | 通用版,精度不足业务需求 | 0 |
| 桌面 / 挂载 / 移动客户端 | 无(§1.2 不需要) | 不需要 | 0 |

→ NC / Seafile 在本业务场景下的**独有价值近零或为负**(增加架构复杂度、维护成本、与业务模型对齐成本)。

### 1.4 MinIO 是标准 S3 → 客户端 / 工具生态完整

| 场景 | 标准 S3 工具(即装即用) |
| --- | --- |
| 桌面 GUI(运维 / admin) | Cyberduck / Mountain Duck / S3 Browser |
| 临时挂载(fallback) | rclone mount / s3fs-fuse / JuiceFS |
| CLI / 自动化 | aws cli / mc(MinIO 官方)/ rclone |
| SDK 接入 | boto3 / minio-py / aws-sdk-js / minio-js |
| 浏览器大文件上传 | uppy.io / tus-js / minio-js multipart |
| 媒体处理 | ffmpeg 直读 `s3://` |
| AI/ML | PyTorch / HuggingFace 直读 `s3://` |
| 跨云 / 灾备 | mc mirror / S3 CRR(active-passive)|

→ MinIO 100% S3 API 兼容,客户端 / 工具生态丰富,**完全覆盖运维 + 旁路 + 未来 AI 数据消费场景**。

---

## 2. Seafile 真正核心价值的精准定位

Seafile 是 **"git for files"** — 文件协作 / 同步 / 版本管理产品,不是对象存储。其真正护城河:

| 价值 | 对应客户场景 | 是否本业务需要 |
| --- | --- | --- |
| Block-level 增量同步 | 大型 Documents / 代码 / 数据库镜像 | ❌(见 §1.1) |
| 桌面同步客户端(seafile-client) | 个人电脑 ↔ 服务器自动后台同步 | ❌(见 §1.2) |
| 挂载盘(seadrive) | 本地呈现整个网盘,按需下载 | ❌(见 §1.2) |
| 移动 app | 个人随时浏览 / 自动备份相册 | ❌ |
| 不可变 commit / rollback | 误删恢复 / 历史回看 | ⚠️ **业务侧 verify §9.2** |
| 加密资料库(client-side encryption) | 高度敏感数据 server 不可见 | ❌(我们走代理 + 审批模型) |
| 资料库 (library) 邀请共享 | 跨团队 / 跨企业协作 | ❌(走飞书 + 审批) |

→ Seafile 的 7 项核心价值,**对本业务场景实际需要的至多 1 项(版本管理)**,且该项可被 MinIO object versioning + 自建 audit 替代。

---

## 3. 新架构详述

### 3.1 组件清单

| 层 | 组件 | License | 自研 / 现成 |
| --- | --- | --- | --- |
| 业务 UI | material-storage web(Vue/React) | 自有 | **自研** |
| 业务后端 | FastAPI + Celery / asyncio | 自有 | **自研** |
| 业务数据库 | PostgreSQL(元数据 / 用户 / 项目 / 审批 / 审计) | PostgreSQL License | 现成部署 |
| 大文件上传组件 | [uppy.io](https://uppy.io) + AWS S3 multipart plugin | MIT | 现成集成 |
| 对象存储 | **Pigsty MinIO fork**(`pgsty/minio`,自 archived 前的 `minio/minio` fork)| **AGPLv3** | 现成部署(选型理由见 [§10](#10-底座选型pigsty-minio-fork)) |
| 事件触发 | MinIO bucket notification → FastAPI webhook | (MinIO 内置,标准 S3 webhook)| 现成 |
| 旁路 worker | FastAPI worker(ffmpeg / Pillow / AI)| 自有 | **自研** |
| 飞书集成 | bridge(已规划)+ MS-FB-001/002/004/007 | 自有 | 已在做 |
| 本地存储 | ZFS dataset on POSIX | CDDL / OpenZFS | 现成 |
| 异地灾备 | MinIO site-to-site replication(active-passive)或 ZFS send-recv 兜底 | AGPLv3 / OpenZFS | 现成 |
| 审计 | material-storage 自建 audit 表(PR #30 重审版) | 自有 | **自研** |

### 3.2 数据流

> "MinIO" 在下文 = [Pigsty MinIO fork](https://github.com/pgsty/minio)(见 §10 选型理由)。链路依标准 S3 协议设计,不与 Pigsty 特定实现耦合 — 若未来 fork 命运不可持续,可换任何 S3-compatible server(escape hatch 见 §10.5、迁移成本评估见 §11 Gap 11)。

**上传**:
```
用户(浏览器)→ uppy 触发 multipart upload
       → 直传 MinIO(经业务后端签 presigned URL)
       → MinIO bucket notification 推 FastAPI worker
       → worker:抽缩略图 / 转代理 / 写 dataset B / 触发 AI / 落 audit
```

**下载**:
```
用户 → 业务 UI → "下载 X" → 业务后端 → 飞书审批(MS-FB-007)
       → 通过 → 业务后端签 presigned URL(短 TTL)→ 浏览器直 MinIO 下载
       → 落 audit(download / signed_url)
```

**敏感目录代理(ADR-0001 §4(b) 演进)**:
```
用户 → 业务 UI → 请求敏感文件
       → FastAPI 代理 stream(不签 URL,服务端控)
       → 落 audit
```

### 3.3 与 ADR-0003 假设的对照

| ADR-0003 弱点应对 | 本架构等价方案 |
| --- | --- |
| 弱点 1:无原生 webhook → MinIO bucket notification | **同**(直接使用,不绕道 Seafile commit object)|
| 弱点 2:无 POSIX 直读 → 主动转码代理版 / dataset B | **同**(旁路 worker 仍生成 dataset B)|
| 弱点 3:无 inotify → MinIO bucket event | **同**(直接使用,不绕道 Seafile)|

→ ADR-0003 §3 的三项工程化应对在本架构下**全部保留**,只是触发器是 "用户直传 MinIO" 而不是 "Seafile 写 S3"。**应对逻辑不变,中间多一层 Seafile 被去除**。

---

## 4. ADR-0003 关系精确说明

ADR-0003 的两条触发证据中:

- **证据 1(NC `oc_filecache` 膨胀)** — **仍然成立**,NC 不进入候选(包括本 ADR 的新架构对比)
- **证据 2(Seafile CE 不支持 S3 backend)** — **仍然成立**,但本 ADR 的结论**不再需要这条证据驱动**:不是"CE 不能用所以升 Pro",而是"Seafile 这一层对本业务都没必要"

ADR-0003 的**结论部分**("收敛到 Seafile Pro")由本 ADR 推翻;ADR-0003 的**调研价值**(NC 排除理由 / Seafile CE 实测 / Pro license 商务接洽)作为历史决策痕迹保留。

ADR-0003 的 §"License / Pro 版前提" 中列的三条 fallback:
1. ~~oCIS 提前~~ — 本 ADR 取消
2. ~~CE + local fs + inotify 回归~~ — 本 ADR 取消
3. ~~MinIO + 自研 Seafile-like 元数据~~ — **接近本 ADR 的方向**,但"Seafile-like 元数据" 在本业务下被业务元数据替代(不需要重新发明 commit / library 概念)

---

## 5. 自研工作量评估

| 模块 | 工作量 | 优先级 |
| --- | --- | --- |
| 业务 UI(浏览 / 上传 / 下载 / 申请 / 审批面板) | 6-10 周(原本就在 ADR-0001 范围)| P0 |
| FastAPI 业务后端(REST + 权限 + 审计 + 飞书桥)| 4-6 周(部分已规划)| P0 |
| 大文件上传(uppy + S3 multipart presigned)| 1-2 周 | P0 |
| 业务后端 ↔ MinIO(presigned URL 签发 / 代理 stream)| 1 周 | P0 |
| 旁路 worker(MinIO event → ffmpeg / Pillow → dataset B) | 3-4 周(原本就要做)| P0 |
| 审计落库(audit-schema 修订版,无 Seafile activity join)| 2 周(简化,比 PR #30 原版少一半)| P0 |
| 飞书审批 + 下载授权(MS-FB-007 修订)| 1-2 周(签 presigned URL 替代 share-link)| P0 |
| admin 后台(用户 / 项目 / 配额 / 审计查询)| 3-4 周 | P1 |
| 视频缩略图 / 抽帧 / 预览 | 1-2 周(旁路 worker 内)| P0 |
| 全文搜索(基于业务元数据)| 1-2 周(PostgreSQL FTS 或 Meilisearch)| P1 |

**总计 P0:~ 20-30 周**,基本与原"Seafile + 自研 material-storage 桥"路径持平,但**去除了 Seafile 学习曲线 / Seafile 二开 / Pro license 接洽 / shadow account 等复杂度**。

---

## 6. 不采纳的替代方案

| 方案 | 不采纳理由 |
| --- | --- |
| **A. Seafile Pro license + black box**(原 ADR-0003)| 业务杀手锏全部不适用(§1.1, §1.2);license 费 + 黑盒依赖;功能层重复 |
| **B. Seafile CE + 外部 wrap**(模型上次"选项 B")| SSO 体验倒退 shadow account;权限模型与业务冲突 |
| **C. Seafile CE + 二开 Seahub + 二开 seafile-server**(模型上次"选项 C+D")| 二开 2-3 月;为业务不需要的功能层付出代价;长期 fork 维护负担 |
| **D. NextCloud CE + MinIO**(上次提到的反弹路径)| `oc_filecache` 风险仍在(ADR-0003 证据 1);功能层重复问题与 Seafile 同理 |
| **E. oCIS + MinIO** | oCIS 自身成熟度待验(v0.5 P1 候选);功能层重复问题同理;增加学习曲线无业务收益 |
| **F. 自建 S3 server(SeaweedFS / Garage / RustFS / AIStor Free 等)替代 MinIO** | **2026-05-16 候选评估后**:Pigsty MinIO fork 胜出(见 [§10](#10-底座选型pigsty-minio-fork));SeaweedFS / RustFS / Garage / AIStor Free 评估结果与不采纳理由列入 §10.4 |

→ 所有"上层文件管理系统"路径(A-E)在业务模型重审后均失去 ROI;**仅保留 MinIO 作存储层**是最干净方案。

---

## 7. 仍需 verify 的事项(业务侧拍板后转 accepted)

### 7.1 [关键] 剪辑师 / 设计师本地工作流确认

> 业务侧问题:剪辑师 / 设计师**是否需要"本地像自己硬盘一样浏览 / 编辑素材后自动同步回服务器"** 的工作模式?

- 若 **不需要**(所有操作走业务 UI 显式下载 / 上传 / 通过 FastAPI 代理流式)→ 本 ADR 直接 accepted
- 若 **需要**(部分角色必须本地后台同步)→ 评估 fallback:
  - (a) 用 rclone 配 MinIO 作"准同步盘"(无 block 增量,但 full-file 同步可用)
  - (b) 二开一个轻量同步守护(用 minio-py + watchdog 实现 inotify ↔ S3 双向 sync,2-4 周)
  - (c) 重新引入 Seafile / NC 作"特定角色的同步前端",但**不作业务主路径** — 等于回到双轨,复杂度反弹

### 7.2 版本管理需求确认

> 业务侧问题:**是否需要 "把整个项目目录 rollback 到上周三某时刻" 的语义?** 还是 **"恢复某个误删的单文件" 就够?**

- 若仅后者 → MinIO object versioning 完美 cover(本 ADR 默认假设)
- 若需要前者 → 需自建"目录级 snapshot" 抽象(基于业务表 + 定时打 ZFS snapshot),~2-3 周;**仍不需要 Seafile**

### 7.3 大文件上传 UX 实测

> 100GB+ 文件用 uppy + S3 multipart,断网重连 / 浏览器关闭恢复实测体验

- 已知 uppy 在 1-10GB 文件场景成熟,100GB+ 边缘情况需 PoC 验证
- 若 uppy 不够 → 评估 tus-js / 自建 multipart 协调层
- 不影响 ADR 结论,影响实施细节

### 7.4 异地灾备 RPO/RTO 要求

> 业务侧确认 RPO/RTO 目标,选择灾备方案

- RPO < 1h:MinIO bucket replication(active-passive)
- RPO 几小时:ZFS send-recv(零额外组件)
- RPO 秒级 + 跨云:MinIO multi-site replication / S3 CRR

---

## 8. 影响范围(已有文档 / 契约 / PR 修订清单)

### 8.1 立即需要修订

| 文档 / PR | 修订内容 |
| --- | --- |
| [audit-schema.md(PR #30)](../audit-schema.md) | §3 cross-system event mapping 整段重写(无 Seafile activity);§7 Seafile activity 字段映射整段删除;§2 ownership matrix material-storage 从 "projection" 变 "full SoT" |
| [file-management-system.md v0.5](../research/file-management-system.md) | §3 收敛后架构重写(无 Seafile);§6.3 F-1 ~ F-6 Seafile-specific findings 移到附录 / 归档 |
| ADR-0001(no-full-custom-web-ui) | "业务 UI" 范围扩大(原假设有 Seahub 作通用 UI 兜底,现在没有)— 加 amendment 段说明业务 UI 需自建大文件上传 / 管理面 |

### 8.2 飞书契约需要重审

| 契约 | 重审动作 |
| --- | --- |
| **MS-FB-006 sso-seafile.md** | **整个契约失去 ground**(Seafile 不再在架构内);bridge 仍提供 OIDC 给 material-storage 业务后端作 RP,不变;**契约可作废或重命名为通用 SSO** |
| **MS-FB-007 approval-seafile.md** | 重写:不再是"approval 通过后调 Seafile API 生成 share-link",而是"approval 通过后 material-storage 签 MinIO presigned URL(短 TTL)发给用户";契约面变 bridge → material-storage REST 单向通知 |
| MS-FB-001(approval)/ MS-FB-002(identity)/ MS-FB-004(SSO) | 不受影响,继续生效 |

需与 feishu agent 协调(开 issue + PR review 流程,见 multi-agent-subproject-pattern)。

### 8.3 PoC scaffold 处置

| 路径 | 处置 |
| --- | --- |
| `material-storage/poc/seafile/` | 归档(保留作历史 / 后悔药);新建 `material-storage/poc/minio/` 作主 PoC |
| `material-storage/poc/nc/`、`ocis/` | 已属归档状态,不动 |
| `material-storage/poc/dataset-gen/` | 继续(与底座无关)|
| `material-storage/poc/tests/inotify_watcher.py` | 归档(不再需要 inotify) |

---

## 9. 实施 Phase 与回滚条件

### 9.1 Phase

| Phase | 范围 | 时间 | 出口条件 |
| --- | --- | --- | --- |
| **Phase A:架构 PoC** | MinIO + uppy 大文件上传 + bucket notification → FastAPI 旁路 worker + 飞书 SSO 业务后端登录 | 2-3 周 | 100GB+ 文件上传可靠;event → worker 链路通;业务 UI 登录 OK |
| **Phase B:业务 MVP** | 业务 UI(浏览 / 上传 / 申请 / 审批面板)+ 飞书审批 + audit 落库 + 项目 / 元数据模型 | 6-8 周 | 一个完整素材生命周期 e2e 跑通 |
| **Phase C:旁路扩展 + 灾备 + admin** | AI 打标 / dataset B / 全文搜索 / 异地灾备 / admin 后台 | 6-10 周 | 生产级可用 |

### 9.2 回滚条件

本 ADR 若出现以下情况,触发**重审 / 部分回退到 Seafile 路径**:

1. **§7.1 verify 发现剪辑师 / 设计师必须本地后台同步,且 rclone / 轻量同步守护体验不可接受** → 引入 Seafile / NC 作"该角色的同步前端"(双轨)
2. **Phase A PoC 中 uppy + S3 multipart 在 100GB+ 文件 / 不稳定网络下不可靠**,且无可行替代 → 评估 Seafile 客户端作上传通道
3. **业务侧发现需要"整个项目目录原子 rollback" 强需求**,且自建 snapshot 抽象不可接受 → 评估 Seafile commit 语义

回滚成本:Phase A 阶段较低(仅 PoC 投入);Phase B 之后回滚成本急剧上升,因此 §7.1 / §7.2 **必须在 Phase A 完成前 verify 清楚**。

---

## 10. 底座选型:Pigsty MinIO fork

### 10.1 决策

底座 = **[Pigsty MinIO fork(`pgsty/minio`)](https://github.com/pgsty/minio)**,AGPLv3,自 archived 前的 `minio/minio` fork。

### 10.2 MinIO 公司商业化进程纪要

| 时间 | 事件 |
| --- | --- |
| 2021-05 | 全部组件 license 从 Apache 2.0 改 AGPLv3 |
| 2025-05 | breaking release 剥离 community edition Web Console UI + 移除 LDAP/OIDC,推到付费版 |
| 2025-10 | 停止发布 community edition Docker images / pre-built binaries |
| **2026-02-12** | GitHub README 标 "**THIS REPOSITORY IS NO LONGER MAINTAINED**",指 AIStor |
| **2026-04-25** | **`minio/minio` GitHub 仓库 archived(read-only)** |

实测 2026-05-16:`gh api repos/minio/minio` → `{"archived": true, "license": "AGPL-3.0", "pushed_at": "2026-04-24"}`。

公司当前产品:
- **AIStor Free**(单机)= **闭源专有**,免费 license
- **AIStor Enterprise**(分布式)= **闭源专有**,付费

→ MinIO 商业化路径是 Seafile CE/Pro 模式的升级版(Seafile 至少保留 CE 仓库活跃,MinIO 直接关闭只读)。**必须避开 AIStor 黑盒陷阱**。

### 10.3 Pigsty MinIO fork 调研事实(2026-05-16 verify)

| 维度 | 数据 |
| --- | --- |
| Fork from | `minio/minio` 在 archived 之前(2025-10-25 fork,提前半年备战) |
| 仓库 | [`pgsty/minio`](https://github.com/pgsty/minio) |
| Stars | 1.5k |
| Open issues | 13(健康) |
| License | AGPLv3(继承 MinIO)|
| Release cadence | **每月一次**:2026-02-14 / 03-14 / 03-21 / 03-25 / 04-17 |
| 最新 release | RELEASE.2026-04-17T00-00-00Z |
| 关键改动 vs MinIO archive 前 | (1) 恢复 embedded Web Console(MinIO 公司剥离);(2) 切换 `georgmangold/console v1.9.1` 社区 fork;(3) 文档 fork [silo.pigsty.io](https://silo.pigsty.io);(4) Docker Hub image + APT/YUM 包(MinIO 公司 2025-10 停发) |
| 维护方 | Pigsty(独立社区,主业是 PostgreSQL 基础设施)|
| 工具兼容性 | **完全兼容**原 MinIO API + CLI(`mc`)+ SDK(boto3 / minio-py / minio-js)+ Console |

### 10.4 不采纳的候选(2026-05-16 评估完成)

| 候选 | 不采纳理由 |
| --- | --- |
| **AIStor Free / Enterprise** | 闭源专有,重蹈 Seafile Pro 黑盒陷阱;license 随时可改;付费(Enterprise) |
| **SeaweedFS** | 32k stars 最成熟,但**架构本质是分布式 file system + S3 gateway**(非原生 object store),边缘 case 行为偏差;v3.95 出现 signature 验证 breaking regression,稳定性需谨慎;**作为兜底次选保留**(见 §10.5) |
| **RustFS** | **Beta / Tech Preview**,官方明确警告不要 critical production;**大文件 sequential read 性能弱于 MinIO**(视频场景踩坑);已知 CPU 异常 issue;商业实体不透明 |
| **Garage** | **Scale ceiling 50-100TB,我们 100TB 在边缘**;duplication-only(3 副本 = 300TB 物理存储);设计目标是 small federated multi-site,非企业素材库 |
| **Ceph RGW** | 部署运维极复杂,100 人 + 100TB 规模 overkill;LGPL |
| **公有云 OSS**(阿里云 / AWS / 腾讯)| 数据 sovereignty + 长期成本;不满足"自托管"前提 |
| ~~OpenMaxIO~~ | 早期 fork,2025 年底最后 commit,已死 |

### 10.5 长期可持续性兜底策略

Pigsty MinIO fork 是 **7 个月新生 fork**,长期可持续性是真风险(Pigsty 团队若没精力,可能 stall)。escape hatch 设计:

1. **协议层耦合**:代码用标准 S3 API + 标准 bucket notification,**不与 Pigsty 特定行为绑定**
2. **数据可迁移**:S3 → S3 用 `mc mirror` 工业级方案,数据格式无 Pigsty 特定锁定
3. **SeaweedFS 作次选**(Gap 11):每季度短 PoC 跟跑,一旦 Pigsty stall,1-2 个月内可切换
4. **AIStor Free 作最后兜底**(虽闭源但 API 兼容):紧急情况短期 swap,保业务连续性,平行招募替代方案

→ Pigsty fork 不是 long-term commitment,是 **"当前最便宜稳妥的选择 + escape hatch 设计完整"**。

---

## 11. 完整链路与 gap 清单

### 11.1 端到端链路图

```
┌────────────────────────────────────────────────────────┐
│  [入口] 用户登录                                         │
│  Browser → material-storage UI                          │
│  → SSO via 飞书 bridge OIDC(MS-FB-004)                 │
│  → material-storage session(audit:admin_session)        │
└────────────────────────────────────────────────────────┘
                          ↓
┌────────────────────────────────────────────────────────┐
│  [浏览] 用户看素材                                       │
│  → 业务 UI → material-storage REST API                   │
│  → 业务权限模型过滤(Gap 5)                              │
│  → 缩略图引 MinIO presigned GET URL(短 TTL)            │
└────────────────────────────────────────────────────────┘
                          ↓
┌────────────────────────────────────────────────────────┐
│  [写] 用户上传                                           │
│  → uppy 触发 S3 multipart(Gap 2)                       │
│  → material-storage 签 presigned PUT URL                 │
│  → 浏览器直传 MinIO                                       │
│  → MinIO bucket notification → FastAPI webhook(Gap 9)   │
│  → 旁路 worker 链:                                       │
│    · ffprobe 元数据 → PostgreSQL                         │
│    · 缩略图 / keyframe(Gap 8)                          │
│    · 720p H.264 代理版 → dataset B(Gap 8)              │
│    · 未来:AI 打标 / embedding                           │
│  → audit:upload + sidecar_task                          │
└────────────────────────────────────────────────────────┘
                          ↓
┌────────────────────────────────────────────────────────┐
│  [读 — 非敏感] 用户下载                                  │
│  → 业务权限 check                                        │
│  → material-storage 签 presigned GET URL(短 TTL)        │
│  → 浏览器直下 MinIO                                       │
│  → audit:signed_url_issued + download                    │
└────────────────────────────────────────────────────────┘
                          ↓
┌────────────────────────────────────────────────────────┐
│  [读 — 敏感] 审批驱动下载                                 │
│  → 业务 UI 申请                                          │
│  → material-storage → 飞书 approval(MS-FB-001/007 重写)│
│  → 审批通过 webhook → material-storage                   │
│  → 签 presigned URL(更短 TTL)+ 通知用户                 │
│    A. 业务 UI 通知中心  /  B. 飞书 IM 卡片(Gap 13)     │
│  → audit:approval + signed_url + download                │
└────────────────────────────────────────────────────────┘
                          ↓
┌────────────────────────────────────────────────────────┐
│  [离职闭环]                                              │
│  飞书 contact.user.deleted_v3 → bridge → material-storage│
│  → 撤销活跃 session                                      │
│  → 加入 presigned URL 黑名单(Gap 1)                    │
│  → audit:resign_revoke                                   │
└────────────────────────────────────────────────────────┘
                          ↓
┌────────────────────────────────────────────────────────┐
│  [灾备]                                                  │
│  → MinIO site replication(active-passive)              │
│  → PostgreSQL 主从复制                                   │
│  → ZFS snapshot 调度兜底                                 │
└────────────────────────────────────────────────────────┘
```

### 11.2 13 个 gap 清单(优先级 + 责任方 + 状态)

| # | Gap | 优先级 | 状态 | 责任方 | 关键点 |
| --- | --- | --- | --- | --- | --- |
| **1** | **Presigned URL 撤销机制** | P0 | 🔴 未规划 | material-storage | S3 presigned 是 stateless,签出无法撤;离职/紧急撤权需 black list 表 + 短 TTL + 关键场景走 FastAPI 代理(可拦截);或用 MinIO STS + revoke |
| **2** | **大文件 multipart upload UX** | P0 | 🟡 选了 uppy,未 PoC | material-storage | 100GB+ 视频 + 浏览器关闭重连 + 断网恢复 + abort 后 orphan part 清理 + 并发调优;uppy 在 10GB 量级成熟,100GB+ 边缘 — Phase A 必跑 |
| **3** | **敏感目录 stream proxy 性能** | P1 | 🟡 设计未细化 | material-storage | FastAPI 服务端 stream(不签 URL,鉴权流式吐),evaluate 单实例并发 stream 数 + 大带宽 worker 模型 + audit 中段策略 |
| **4** | **飞书契约 MS-FB-006 / MS-FB-007 重审** | P0 | 🔴 必须改 | material-storage + feishu agent | MS-FB-006 sso-seafile **作废**;MS-FB-007 改为 bridge → material-storage 单向通知 approval 状态变更,material-storage 自签 presigned URL;开 issue 走 PR review 协调 |
| **5** | **业务权限模型(用户 ↔ 资源)** | P0 | 🔴 未规划 | material-storage | 飞书 SoT 给 user/group/department,不给 "用户能访问哪些资源";需自建 resource access policy(简化 ABAC);至少 user / group / project / role / resource 五元 + 规则组合 |
| **6** | **桌面 / 移动端体验降级** | P2 | 🟡 §7.1 verify | 业务侧决策 | 业务侧确认全走 web → 关闭;否则 fallback rclone / Cyberduck / minio-client + STS;不在本 ADR 范围 |
| **7** | **业务元数据搜索** | P1 | 🟡 已规划(Phase C) | material-storage | 视频/图片业务,基于业务元数据(项目/客户/标签/拍摄日期/摄影师)多维搜索;非文档全文;PostgreSQL FTS 或 Meilisearch |
| **8** | **预览生成 / 转码 worker pool** | P0 | 🟡 已规划(Phase B)| material-storage | 缩略图 + keyframe + 720p H.264 代理版 + ffprobe 元数据;worker pool 调度 + 重试 + 死信队列;dataset B 空间预算 |
| **9** | **MinIO bucket notification 可靠性** | P0 | 🟡 PoC 未跑 | material-storage | Phase A 必验:webhook 重试策略、网络抖动、worker 重启时事件积压、idempotency(audit dedup_key 配合) |
| **10** | **Audit 表 schema 重写** | P0 | 🟡 PR #30 待修订 | material-storage | 去 Seafile activity 字段;ownership matrix 简化(全权 SoT);事件枚举:upload / download / proxy_download / approval_state / sidecar_task / admin_session / signed_url_issued / signed_url_revoked / resign_revoke |
| **11** | **Pigsty fork 长期兜底** | 一直跟 | 🟢 协议层耦合 + escape hatch | 架构层 | 见 §10.5;每季度短 PoC 跟跑 SeaweedFS,定期 verify mc mirror 迁移路径可达;无即时动作,长期 invariant |
| **12** | **业务 UI 核心 features 范围** | P0 | 🟡 ADR-0001 amendment 范围 | material-storage | 浏览 / 搜索 / 上传 / 下载(单+批+打包)/ 申请审批 / 历史 / admin 后台 / 通知中心;Phase B 主战场,6-10 周 |
| **13** | **通知通道(审批结果给用户)** | P1 | 🟡 未拍板 | material-storage + feishu agent | A. 业务 UI 通知中心(主)/ B. 飞书 IM 卡片推送(增强,需新契约);推荐 A+B |

### 11.3 与飞书集成的接缝总览

| 接缝 | 契约 | 状态 |
| --- | --- | --- |
| 用户认证(material-storage 作 OIDC RP)| MS-FB-004 SSO | ✅ v1 已就绪,可复用 |
| 用户身份解析(open_id → user info) | MS-FB-002 identity | ✅ v1 已就绪 |
| 审批申请发起 | MS-FB-001 approval | ✅ v1 已就绪 |
| **审批通过后授权下载** | **MS-FB-007 approval-seafile** | 🔴 **重写**:bridge 不再调 Seafile,改通知 material-storage,自签 presigned URL(Gap 4)|
| ~~Seafile SSO 集成~~ | ~~MS-FB-006 sso-seafile~~ | ❌ **作废**(无 Seafile)(Gap 4) |
| 离职闭环 | 已在 MS-FB-002 内 | ✅ 行为按 §11.1 落地 |
| (新)审批结果 IM 推送 | **MS-FB-?**(新契约) | 🟡 Gap 13 拍板后开 |

---

## 12. 关联

- 本 ADR 草案对话纪要(2026-05-16,主对话 "rushes-main")
- 用户决策原文(2026-05-16):"Seafile 在视频/图片业务下的价值重审"
- [ADR-0003 §"License / Pro 版前提" 第 3 条 fallback "MinIO + 自研 Seafile-like 元数据"](./0003-seafile-only-poc.md) — 本 ADR 是该 fallback 的精确版(去 "Seafile-like 元数据" 因业务无需该抽象)
- PR #30(audit-schema v1)— 待重审
- 上游源码调研痕迹:`<workspace>/seafile-upstream/seafile-server/`(本地 vendor,不进仓库)— 调研结论已收敛入本 ADR,后续可清理

---

## Verify 后转 accepted 的 checklist

- [ ] §7.1 剪辑师 / 设计师本地工作流需求,业务侧拍板
- [ ] §7.2 版本管理 rollback 粒度,业务侧拍板
- [ ] §7.3 uppy + S3 multipart 在 100GB+ 文件实测 PoC 通过
- [ ] §7.4 RPO/RTO 目标,业务侧拍板
- [ ] §8.2 与 feishu agent 同步 MS-FB-006 / MS-FB-007 重审,review 通过
- [x] §7.1 ~ §7.4 业务侧 verify(2026-05-16 全 ✅)
- [x] §7-bis.1 / §7-bis.2 产品决策落地(2026-05-16)
- [x] Phase A.2 PoC 跑通:Pigsty MinIO + nginx + Caddy + Console + uppy 632 MiB 跨境 multipart + bucket notification → FastAPI(2026-05-16)
- [x] OpenFGA PoC verified:28/28 checks pass(2026-05-16)— Gap 1 / Gap 5 方案确认
- [x] 与 feishu agent 协调:MS-FB-006 作废(PR #39 merged)+ MS-FB-007 v2 重写(PR #37 merged)+ MS-FB-008 IM 推送(issue #36 in flight)
- [x] [ADR-0006 — Phase B 技术选型](./0006-phase-b-tech-stack.md)起草(2026-05-16)
- [ ] §11 Gap 清单按 P0/P1/P2 开 GitHub issue(Phase B-2 启动前)
- [ ] PR #30 audit-schema 修订版(Gap 10,基于 OpenFGA tuples + 业务事件;Phase B-2)
- [ ] file-management-system.md 重写 v0.6(可推迟,ADR-0005/0006 已 supersede)
- [ ] ADR-0003 加 amendment 段指向本 ADR

→ **ADR-0005 accepted**(2026-05-16 全部核心 verify 通过)。Phase B 启动 blocking 在 ADR-0006 团队 review。
