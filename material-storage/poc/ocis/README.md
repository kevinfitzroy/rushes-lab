# ocis/ — oCIS PoC 路线(骨架)

⚠️ **本路线依赖 feishu-integration 的 bridge OIDC endpoint 就绪**;现阶段 docker-compose 仅为骨架,实际启动要等飞书 agent 实施完 ADR-0002 的 5 个 OIDC 端点。

## 当前可立即跑的部分

不接 OIDC、用 oCIS 内置 IDM(用户名密码)起 oCIS 本身,验证:

- 部署 / 启动 / Web UI 可用
- decomposedfs 在本地存储下的基本读写
- xattr 元数据机制是否在底层 filesystem 上完整可用(本地 ext4 / btrfs / ZFS 测一下)

**步骤(不接 OIDC,验证启动):**

```bash
cp ../.env.example ../.env
# 临时改 .env:OCIS_OIDC_ISSUER 指向 dummy(待 bridge 就绪再改)

# 移除 docker-compose.yml 里 OCIS_OIDC_ISSUER 那行(临时,验证启动)
# 或者参考 owncloud 官方"single-process bootstrap mode" 文档跑 ocis init

docker compose up -d
docker compose logs -f ocis
```

> oCIS 严格要求 OIDC provider,**不接 OIDC 时只能跑 init 流程或带 IDP 自带模式**;具体细节落 PoC 时 dig out。

## 接 bridge OIDC(等 feishu 实施完毕)

```bash
# 1. 确认 bridge 已暴露:
curl https://rusheslab.taoxiplan.com/oidc/.well-known/openid-configuration

# 2. .env 里填 OCIS_OIDC_ISSUER + OCIS_OIDC_CLIENT_ID,确认与 bridge 静态 client 配置一致
# 3. 启动
docker compose up -d

# 4. 浏览器访问 OCIS_URL → 应跳转 bridge → 跳转飞书 → 完成 OAuth → 跳回 oCIS,JIT 建账号
```

## 灌数据集

oCIS decomposedfs **不**像 NC 那样可以直接 `cp` 文件到 datadirectory 然后 `files:scan`。原因:文件元数据要 xattr + 内部 metadata 索引,直接 `cp` 不会进 oCIS 视图。

候选方案(PoC 验证选哪个):

| 方案 | 描述 | 备注 |
| --- | --- | --- |
| (A) 通过 oCIS WebDAV API 上传 | 用 curl/python 调 PROPPATCH/PUT,逐文件灌入 | 慢,但是"正经"路径 |
| (B) `ocis decomposedfs` CLI 重建索引 | 把文件放到 decomposedfs 期望布局后,跑内部命令重建 | 需要确认有这种 CLI(待 PoC 校验) |
| (C) 用 oCIS rclone backend 大批上传 | rclone 有 owncloud / WebDAV backend | 第三方工具,资源开销小 |

issue #13 验收任务之一:**确定 oCIS 灌数据的工程路径** + 50w 文件下耗时。

## 性能验收(issue #13)

待 OIDC 就绪 + 数据灌入路径确认后跑:

- 目录浏览 / 上传 / 缩略图生成耗时(对照 NC 同指标)
- **xattr 元数据机制在 NFSv4 下完全可用**(关键!NFSv4 需 enable xattr)
- 客户端兼容性:NC desktop / ownCloud desktop / 移动客户端
- NFS 客户端缓存对元数据一致性影响
- 与 bridge OIDC 集成 e2e(配合 #14)

## 关联

- 飞书 bridge OIDC ADR:[`../../../rushes-spec/feishu/decisions/0002-bridge-as-oidc-provider.md`](../../../rushes-spec/feishu/decisions/0002-bridge-as-oidc-provider.md)
- material-storage SoT ADR:[`../../../rushes-spec/material-storage/decisions/0002-feishu-contacts-as-identity-source.md`](../../../rushes-spec/material-storage/decisions/0002-feishu-contacts-as-identity-source.md)
- v0.3 §9 oCIS NFS 最小部署配置(本目录是其落地版本)
