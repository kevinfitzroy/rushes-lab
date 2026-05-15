# material-storage PoC

文件系统选型 PoC 代码骨架 —— NC + oCIS 两路线串行/并行实测。配合 [`../../rushes-spec/material-storage/research/file-management-system.md`](../../rushes-spec/material-storage/research/file-management-system.md) v0.3 验收。

## 适用范围

| 阶段 | 范围 | 适合在哪跑 |
| --- | --- | --- |
| **Stage 1 功能 PoC** | 部署 / Web 进 / inotify 旁路 / 敏感下载代理 e2e | 小机器即可(~4GB RAM,几百文件数据集),例如 47.109.30.236 |
| **Stage 2 性能 PoC** | preview:generate-all / oc_filecache 增长 / 桌面同步冲突 / 50-100w 文件全量扫描 | 至少 16GB RAM / 8 核 / 1-2TB NVMe(见 v0.3 §10 PoC 任务硬件建议) |

issue #11/#12/#13/#14 默认指 Stage 2;Stage 1 在新一轮配套实测前可以用本仓库代码先跑通端到端流程。

## 目录布局

```
poc/
├── .env.example              敏感变量模板;运行前 cp 成 .env(.gitignore 已覆盖)
├── dataset-gen/              合成数据集生成器(issue #11)
├── nc/                       Nextcloud 路线 docker-compose + 配置(issue #12)
├── ocis/                     oCIS 路线 docker-compose + 配置(issue #13,依赖 bridge OIDC 就绪)
└── tests/                    通用测试脚本(inotify watcher 等,issue #14 一部分)
```

## 前置条件

| 项 | 要求 | 备注 |
| --- | --- | --- |
| Docker | ≥ 24 | 容器化部署 |
| docker compose | v2(plugin 形式,不要 v1) | |
| Python | 3.10+ | dataset-gen / tests 用 |
| 磁盘 | dataset 模式而定;sparse 模式只占 metadata,realistic 模式占真实视频 × N | 见 dataset-gen/README.md |
| 网络 | 各路线 8081/8082 端口默认对外暴露(可改 .env) | |
| 飞书 bridge OIDC | oCIS 路线需要 | 等 [feishu-integration](../../feishu-integration/) 实施完成 |

## 部署模式

**默认 = 单机串行**(资源紧张的 PoC 机器):

```
# 先跑 NC
cd nc/ && cp .env.example .env && vim .env  # 填密码 + host
docker compose up -d
# ... 跑测试,记录指标 ...
docker compose down

# 切到 oCIS
cd ../ocis/ && cp .env.example .env && vim .env
docker compose up -d
# ...
```

资源够则可以**并行**跑两路线(不同端口),互不干扰。

## 工作流

1. **准备数据集**:`cd dataset-gen/` 生成数据到 `${DATA_ROOT}/dataset-<n>`,产出 manifest。
2. **跑一条路线**(NC 或 oCIS):配置 `.env` → `docker compose up -d` → 浏览器进。
3. **挂数据集**:
   - NC:把 dataset 目录拷/挂到 NC datadirectory 下;`docker exec nc-app php occ files:scan --all`
   - oCIS:把 dataset 拷/挂到 decomposedfs storage 路径下(需 oCIS 内部命令重建索引,具体路径 PoC 验证)
4. **跑 baseline tests**:`tests/inotify_watcher.py` 等。
5. **回写测试结果**到 v0.3 §6.4(新章节,待建)。

## 敏感凭据

**全部走 env vars,不入仓库**:

- `NC_ADMIN_PASSWORD`、`NC_DB_PASSWORD` 等数据库/admin 密码
- `OCIS_OIDC_ISSUER` 指向 bridge 真实 host
- 飞书 `APP_SECRET` / `ENCRYPT_KEY` / `VERIFICATION_TOKEN` 不在本子目录使用,留在 `feishu-integration/`

`.gitignore` 已覆盖 `.env`,提交前自查:`git status` 确认无 `.env` / `*.pem` 被加入。

## 关联

- v0.3 调研:[`../../rushes-spec/material-storage/research/file-management-system.md`](../../rushes-spec/material-storage/research/file-management-system.md)
- PoC 任务清单:GitHub issues #11(foundation)/ #12(NC)/ #13(oCIS)/ #14(shared)
- 飞书 bridge OIDC ADR:[`../../rushes-spec/feishu/decisions/0002-bridge-as-oidc-provider.md`](../../rushes-spec/feishu/decisions/0002-bridge-as-oidc-provider.md)
