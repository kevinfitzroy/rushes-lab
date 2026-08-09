# Handoff:Wave 1 + Wave 2 实施完毕,交给 review agent 复测(2026-08)

> 写给接手 **review/gatekeeper** 角色的 agent:本阶段(Wave 1 #149-#152 + Wave 2 #153-#154)已全部实施、merge 完毕、issue 已关。
> 你的任务是**复测 + 补跑容器集成测试 + 发现回归及时提新 issue**。读完本文件 + 各 PR 描述即可开工,不要泛泛重读全仓。
> 创建:2026-08-09(material-storage 协调者)。决策依据:ADR-0007 / ADR-0008 / tracking issue #155。

## 0. 三分钟现状

- **main = `a8cd66e`**,8 个 PR 全部 squash merge,issue #149-#154 全部 CLOSED(gatekeeper 已关)。
- 产品:素材库系统(FastAPI + React 19 + PG16 + MinIO + OpenFGA + Redis/arq)。方向:去飞书、局域网自建、标签盲搜优先(ADR-0007/0008)。
- **最大遗留:容器集成测试约 60 个未在任何环境跑过**(实施机无 docker)。**review 的主要工作量 = 在 server2(有 Docker 29.5)或 CI 上补跑全量测试**。

## 1. Merge 链(main = a8cd66e,时间序)

| Commit | PR | 内容 |
| --- | --- | --- |
| `fbe1f66` | #158 | #149 本地认证:argon2id 登录/改密/强制改密、Redis 双维限流、登录页+守卫 |
| `2cc9ca2` | #160 | #150 管理后台:用户/组 CRUD、`users.username`、临时密码、picker 本地化、`revoke_user_completely` 修复 |
| `6772692` | #159 | #152 生产部署:内网 compose/env 模板、ADR-0008 分层(P0 卷放置 + P1 缩略图拆分)、备份脚本、#69 dev_bootstrap 修复 |
| `d60ef96` | #157 | #151 标签盲搜:跨 folder 搜索(can_view 硬验收)、打标/备注、migration 0007 |
| `7721f35` | #163 | alembic 双 head 修复(0008 down_revision 0006→0007) |
| `14b0a9e` | #162 | #154 飞书下线:11 文件删除、OIDC provider 留口、migration 0010 |
| `a8cd66e` | #161 | #153 通知中心:in-app 通知 + 可选 SMTP、Bell/未读轮询 |

alembic 链:**0006 → 0007(#151) → 0008(#150) → 0010(#154)**;0009 空置(#153 无 migration)。

## 2. ⭐ Review 重点(按风险排序)

### 2.1 容器集成测试全量未跑(首要任务)
实施机无 docker,以下文件全部只写了没跑过,PR 里均标注"待 docker 环境":
- `tests/test_v4_permissions.py`(#148 的回归网,18 个)
- `tests/test_local_auth_integration.py`(#149,14 个,DB-gated)
- `tests/test_directory.py`(#150,7 个,OpenFGA 502 依赖)
- `tests/test_search_labels.py`(#151,9 个,含 sensitive 零泄露三条路径)
- #153 的通知 e2e(2 个:申请→审批→结果→mark-read 全链路 + SMTP no-op)

**跑法**(server2 或本地 compose):`docker exec ms-api pytest tests/ -v`。注意 `force-recreate` 后容器内 dev 依赖会丢,需重装;`test_v4_permissions` 依赖 seed 固定 UUID + 已 push 的 OpenFGA model。

### 2.2 跨 PR 交互点(merge 后才是真身,建议重点读)
- **通知链路**:#153 的 in-app 调用点在流程主体(`routers/approvals.py` 3 端点 + `routers/folders.py` 邀请),`services/notifications.py` 独立模块。#162 已删 IM 卡片与 `approvals_notify.py`/`invite_notify.py` 文件。**验收:申请→审批→结果通知全链路;`feishu_im_enabled`(已删)关闭时通知照常。**
- **share 通知已死**:#162 删除 `receive_open_ids`/`message` 概念,share 变纯链接;#161 rebase 时同步删除了 share 通知写路径 —— 不要期望分享通知存在。
- **auth**:#149 的 `services/local_auth.py` + `routers/auth.py` 只加不删;#154 把 OIDC 抽象为 `settings.oidc_provider`(单 dict,默认空 = 纯本地)。`X-User-Id` dev 通道保留(仅 env=dev)。
- **settings.py 合并结果**:`smtp_*`(#153)+ `minio_thumbnail_*`(#152)+ `oidc_provider`(#154)+ auth 配置(#149)共存;`feishu_*` 全删。
- **users 表**:`username`(#150,unique nullable)+ `oidc_sub`(#154,nullable)+ `feishu_open_id`/`feishu_union_id`(保留只读)。老飞书用户 username 为 NULL —— 登录按 email(含@)或 name 匹配。

### 2.3 已知坑 / flaky(复测时别误判为回归)
- `tests/test_passwords.py::test_temp_password_has_both_cases_and_digits`:**main 基线 flaky**(随机 12 位密码单例断言,实测 1/5 失败)。非本阶段引入。
- pytest 本机跑有 ~16 个 `socksio` 环境预存 errors(非业务失败,需装 socksio 或忽略)。
- e2e `bob download sensitive (via invited can_view)` 403 = **既存测试-模型不匹配**(approval 只授 viewer,`can_download` 需 downloader),main 上从未执行到该步,非本阶段引入。
- e2e 跨轮不幂等 + large-file `KeyError: upload_id`:#69 已知,非本阶段引入。
- #154 的 rebase 曾抓到并删除 2 个过时用例(`TestFmtSubject::test_department/test_organization` 仍断言已下线的 subject kind)—— 若你在别处看到 department subject 断言,同样是过时代码,对照 `permissions-model-v4.md` 修订版。

### 2.4 遗留事项(不是 review 失败,是明确的后续)
1. **server2 存量 OpenFGA subject 还是 `user:<open_id>`**:迁移脚本 `scripts/migrate_subjects_to_uuid.py`(#148 产出)就绪但**未执行**。内网 cutover 时先跑迁移(输出前后 `list_objects` diff)再切本地登录。
2. **飞书旧 app 注销**(`cli_aa8c58fae5391be7`):步骤清单在 PR #162 描述,需人工登录飞书开放平台执行。
3. **department 轴**:写入路径已删(#154),存量 tuple **未迁移**(OpenFGA store 里仍有);`USER_DIRECT_RELATIONS` 保留 `("department","member")` 供离职清理。判断存量影响一律查 OpenFGA store,不要查 audit_events。
4. **备份脚本** `backup_prod.sh`(#152):mc mirror 依赖 HDD 挂载点,内网首装时验证。
5. **#147**(feishu agent 日落知会):issue 状态需确认;feishu-integration 目录未动,仍属 feishu agent。
6. **PR #156**(handoff docs):open,与代码无关。

## 3. 环境与命令

- 实施机(macOS):**无 docker/容器运行时** —— 本机只能跑单元测试(`uv run pytest`,缺 .env 时 env 注入或临时 `cp .env.example .env` 跑完删)。
- **server2**(`8.156.34.238`):Docker 29.5,ssh 免密可用,凭据见 workspace 根 `server.md`(仅本地)。全量容器测试在此跑最顺;`.env` 是手工真值,deploy 默认不覆盖。
- 部署一条龙:`cd material-storage/api && bash scripts/deploy_server2.sh`(step 6/7/8 的 ⚠ 是已知非阻塞,只关心新出现的红 ✗)。
- lint/mypy 基线(以 merge 后 main 为准):ruff ~339 / mypy ~132,各 PR 均已持平或更优。
- 本机 worktree 布局(已完成使命,可清可留):`rushes-lab-149-auth / 150-admin / 151-labels / 152-prod / 153-notify / 154-feishu-removal`;主 checkout `rushes-lab/`(main)。

## 4. 流程合规记录(本阶段已遵守)

- 全部 commit 身份 `Evan <kevinfitzroy715@gmail.com>`,无 zklink 邮箱;push 走 socks5 代理(`GIT_SSH_COMMAND='ssh -o ProxyCommand="nc -X 5 -x 127.0.0.1:10809 %h %p"'`);git.lock 协议全程执行。
- 敏感红线:无 .env / secret / 顾客数据进 commit、issue、PR;deploy heredoc 凭据已清(占位符),真值未进树。
- 并行协调:6 个独立 worktree,registry 文件(App.tsx/hooks.ts/labels.ts)冲突全部按 small-append 取双方新增解决;migration 撞号(0007/0008)与双 head 已修复。

## 5. Review 完成标准

1. server2 上 `docker exec ms-api pytest tests/ -v` 全量跑通(容器依赖测试绿,基线 flaky 除外)
2. 通知全链路 e2e 通过(申请→审批→通知→mark-read;SMTP no-op)
3. 纯本地登录 e2e 通过(无飞书登录入口后,登录/改密/强制改密/限流)
4. 发现的新回归 → 按 bug.yml 模板提 issue(先搜重,同根因合并),不要直接改代码
5. 全部通过后:本文件使命结束,可删
