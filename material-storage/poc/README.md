# material-storage PoC

> ⚠️ **大部分已成历史**(2026-05-17)。本 README 描述的 "v0.5 Seafile only PoC" 路线已被 [ADR-0005](../../rushes-spec/material-storage/decisions/0005-drop-seafile-middle-layer-minio-only.md) **supersede** — 后续不再使用 Seafile / NC / oCIS 任一文件管理底座,改走 **自研 FastAPI/React + MinIO 直存** 路线。
>
> **仍在 dev 用**:
> - [`minio/`](./minio) — docker-compose 起 MinIO + OpenFGA,本地 dev 依赖
> - [`openfga/`](./openfga) — 权限模型源 `store.fga.yaml`,被 api 服务引用
>
> **历史参考**(被 ADR-0005 弃用):[`seafile/`](./seafile) / [`nc/`](./nc) / [`ocis/`](./ocis) / [`dataset-gen/`](./dataset-gen) / [`tests/`](./tests)
>
> 业务后端 / 前端见 [`../api/`](../api) + [`../web/`](../web)。

---

以下是 **v0.5 Seafile-only PoC 阶段的原文**,保留作历史决策上下文。

---

文件系统选型 PoC 代码骨架 —— **v0.5 收敛 Seafile (Pro Edition) 单线**。配合 [`../../rushes-spec/material-storage/research/file-management-system.md`](../../rushes-spec/material-storage/research/file-management-system.md) v0.5 + [ADR-0003](../../rushes-spec/material-storage/decisions/0003-seafile-only-poc.md) 验收。

## 适用范围

| 阶段 | 范围 | 适合在哪跑 |
| --- | --- | --- |
| **Stage 1 功能 PoC** | 部署 / Web 进 / S3 backend 工作验证 / bucket event 旁路 e2e | 小机器即可(~4GB RAM,几百文件数据集) |
| **Stage 2 性能 PoC** | 50-100w 文件 / 桌面同步冲突 / 全链路延迟 P50/P95 / Web UI 响应 | 至少 16GB RAM / 8 核 / 1-2TB NVMe;实测部署机 8.156.34.238(14GB/8c/2TB NVMe) |

[Issue #23](https://github.com/kevinfitzroy/rushes-lab/issues/23) 是 PoC-Seafile 主追踪 issue。

## 目录布局

```
poc/
├── .env.example              敏感变量模板;运行前 cp 成 .env(.gitignore 已覆盖)
├── dataset-gen/              合成数据集生成器(Issue #11)
├── seafile/                  Seafile Pro + 本地 MinIO 路线(v0.5 唯一,Issue #23)
├── nc/                       Nextcloud 路线(v0.5 退出 PoC,Issue #12 关闭;目录保留作历史参考)
├── ocis/                     oCIS 路线(v0.5 P1 长期方向;Pro license 应急可 promote,Issue #13)
└── tests/                    通用测试脚本(Issue #14 一部分)
```

## v0.5 路线变化(2026-05-15 用户决策 + PoC 实测)

[v0.5 file-management-system](../../rushes-spec/material-storage/research/file-management-system.md) + [ADR-0003](../../rushes-spec/material-storage/decisions/0003-seafile-only-poc.md) 收敛:

- ✅ **Seafile Pro + 本地 MinIO(S3 backend)** — 唯一首批 PoC
- ❌ **Nextcloud** 退出(`oc_filecache` 膨胀 #7312 与本项目数据增长方向冲突)
- 🟡 **oCIS** 维持 P1(若 Seafile Pro license 不可获取则 promote)
- 🟡 **Seafile CE** P1 应急(实测无 S3 backend code path,仅 fallback 用,F-X)

## 前置条件

| 项 | 要求 | 备注 |
| --- | --- | --- |
| Docker | ≥ 24 | 容器化部署 |
| docker compose | v2(plugin 形式,不要 v1) | |
| Python | 3.10+ | dataset-gen / tests 用 |
| 磁盘 | 200GB+(50w 文件)/ 400GB+(100w 文件) | 见 seafile/README.md §资源建议 |
| 网络 | Seafile 6083 + MinIO Console 6901 默认对外(可改 .env);MinIO S3 API 仅 docker network 内 | F-6 端口策略 |
| **Seafile Pro license** | 必需(2026-05-16+ 接洽销售) | CE 不支持 S3 backend,F-X |
| 飞书 bridge OIDC | Seafile OAuth2 集成需要 | 等 [feishu-integration](../../feishu-integration/) + [Issue #24](https://github.com/kevinfitzroy/rushes-lab/issues/24) |

## 部署模式

**v0.5 单条路线,不再串行/并行多底座**:

```
cd seafile/
docker compose --env-file ../.env up -d
# ... 等 init ~5min,然后跑 7 项验收 ...
docker compose --env-file ../.env down -v   # 重置时用
```

详细启动 + 配 S3 backend + 7 项验收清单见 [`seafile/README.md`](./seafile/README.md)。

## 工作流

1. **准备数据集**:`cd dataset-gen/` 生成数据到 `${DATA_ROOT}/dataset-<n>`,产出 manifest
2. **部署 Seafile Pro + MinIO**:配置 `.env` → `docker compose up -d`(用 `--env-file ../.env`)
3. **配 S3 backend**:手编 seafile.conf 加 `[block_backend]+[commit_object_backend]+[fs_object_backend]` 三节(F-4);重启 seafile
4. **灌数据集**:通过 Seafile API(`seaf-cli sync` / WebDAV / Web UI 三选一)
5. **跑 7 项验收测试**:见 seafile/README.md
6. **回写测试结果**到 v0.5 §6.3(新建实测记录小节)

## 敏感凭据

**全部走 env vars,不入仓库**:

- `SEAFILE_ADMIN_PASSWORD` / `SEAFILE_DB_PASSWORD` / `MINIO_ROOT_*`
- `OCIS_OIDC_ISSUER` 指向 bridge 真实 host(若 promote oCIS 路线)
- 飞书 `APP_SECRET` / `ENCRYPT_KEY` / `VERIFICATION_TOKEN` 不在本子目录使用,留在 `feishu-integration/`

`.gitignore` 已覆盖 `.env`,提交前自查:`git status` 确认无 `.env` / `*.pem` 被加入。

## 关联

- v0.5 调研:[`../../rushes-spec/material-storage/research/file-management-system.md`](../../rushes-spec/material-storage/research/file-management-system.md)
- ADR-0003 Seafile only PoC:[`../../rushes-spec/material-storage/decisions/0003-seafile-only-poc.md`](../../rushes-spec/material-storage/decisions/0003-seafile-only-poc.md)
- PoC 任务追踪:[Issue #23](https://github.com/kevinfitzroy/rushes-lab/issues/23) PoC-Seafile,[Issue #11](https://github.com/kevinfitzroy/rushes-lab/issues/11) 数据集生成,[Issue #14](https://github.com/kevinfitzroy/rushes-lab/issues/14) 共享 e2e
- 飞书集成准备:[Issue #24](https://github.com/kevinfitzroy/rushes-lab/issues/24)(OAuth2 SSO + 下载审批桥接)
- 飞书 bridge OIDC ADR:[`../../rushes-spec/feishu/decisions/0002-bridge-as-oidc-provider.md`](../../rushes-spec/feishu/decisions/0002-bridge-as-oidc-provider.md)
