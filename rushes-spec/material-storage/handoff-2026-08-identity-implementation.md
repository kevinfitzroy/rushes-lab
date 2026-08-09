# Handoff:身份自建 + 标签盲搜 + 生产化实施(2026-08 阶段)

> 写给刚接手本阶段(#147-#155)任务的 agent:读完本文件 + 你的 issue 即可开工,**不要泛泛重读全仓**。
> 创建:2026-08-09(material-storage agent)。阶段结束后本文件可删。
> 任务总控:**tracking issue #155**;决策依据:ADR-0007 / ADR-0008 / 调研 v0.3(PR #146 已 merge)。

## 0. 三分钟现状

- 产品:素材库系统(FastAPI + React 19 + PG16 + MinIO + OpenFGA + Redis/arq)。Phase B 功能完整(上传/权限/审批/分享/审计/缩略图),曾在公网 server2 dogfood。
- **2026-08-09 决策(已生效,不要再辩论):**
  1. **生产改局域网部署**(egress 有无待定,按"可完全离线运行"设计)
  2. **弃用飞书**(ADR-0007):身份/组织/通知全自建;飞书代码随 #154 下线;feishu-integration 日落(知会 issue #147,等对方 ack)
  3. **产品重心校正**:储存/下载/使用/分享方便 + **标签盲搜** > 权限管理。v4 权限体系保留不拆、最小使用;高隐私功能(sensitive 邀请制)早期可能不启用
  4. **存储分层**(ADR-0008):2TB SSD = PG 元数据 + 缩略图;HDD = 原片
- 工程拆解:Wave 0 地基 **#148** 先行(单 agent)→ Wave 1 **#149-#152** 四路并行 → Wave 2 **#153/#154** 收尾。

## 1. 必读(按序,约 60 分钟)

1. 本文件
2. **你的 issue**(#148-#154 之一)—— 范围 / 不做 / 验收 / 冲突提示都在里面
3. `decisions/0007-drop-feishu-self-built-identity.md`(决策全文 + 下线清单)
4. `ROADMAP.md` 顶部 "2026-08-09 方向校正" 节 + "已知坑" 节(碰到怪行为先搜,每条坑标了引入的 PR 号)
5. 按 issue 选读:#148 必读 `permissions-model-v4.md` + `poc/openfga/store.fga.yaml`;#152 必读 `ops-manual.md` + ADR-0008;#151 必读 ROADMAP 待办 "标签 + 盲搜" 节

**不需要读:** `rushes-spec/feishu/` 全部(日落中)、`poc/seafile/`(废弃)、`refs/`(本地私有,不在仓库)。

## 2. 开工前一小时 checklist

```bash
# 1. clone + 仓库级身份(新机器的 SSH 密钥/凭据问 user,在 workspace 本地 git.md / server.md)
git clone git@kevinfitzroy.github.com:kevinfitzroy/rushes-lab.git
cd rushes-lab
git config user.name "Evan" && git config user.email "kevinfitzroy715@gmail.com"   # 首次 commit 前必须

# 2. 独立 worktree(多 agent 并行硬隔离;不要在别人的 worktree 里干活)
git worktree add ../rushes-lab-<topic> -b feat/<topic> origin/main

# 3. 起本地全栈
cd material-storage/poc/minio && docker compose up -d          # MinIO + OpenFGA + nginx
cd ../../api && cp .env.example .env                           # 填值(server.md 有真值)
docker compose up -d && docker compose exec api alembic upgrade head

# 4. 验证基线绿(全权限回归网)
docker exec ms-api pytest tests/ -v
```

## 3. 全局工程规则(违反会被 review 打回)

- **git 协议**:写操作前取 lock(`.claude/agent-locks/git.lock`,60min,协议见 `rushes-spec/feishu/COLLABORATION.md` §9);不直推 main;`git add <具体路径>` 不用 `-A`;commit 前四件自检(branch / email / lock / tree)
- **测试**:单元 `uv run pytest`;集成 `docker exec ms-api pytest tests/ -v`(`test_v4_permissions` 必须容器内,依赖 seed 固定 UUID + 已 push 的 OpenFGA model);`pyproject.toml` 的 asyncio `loop_scope=session` 是修 asyncpg cross-loop 的既有配置,**勿改**
- **lint**:PR 前 `uv run ruff check .` + `uv run mypy app`(strict)
- **registry 文件**(并行冲突热点):`web/src/App.tsx`、`web/src/api/hooks.ts`、`web/src/lib/labels.ts` —— small-append 风格,PR 前 rebase
- `audit.write()` 内部自带 commit,调用方不要再 commit
- 服务实例走 `app.state` + `app/deps.py` DI,不要模块级单例
- 权限改动成对 grep `permissions.check` **和** `list_objects` 调用点(漏 list_objects = 有权限但列表不可见)
- 系统 admin 直通模式照抄:`allowed = is_system_admin or await permissions.check(...)`
- **不要碰**:`feishu-integration/`(#147 未 ack 前仍属 feishu agent);`poc/seafile/`;给飞书加任何新功能;权限体系镀金(方向校正:最小使用);spec 里写公司真名/客户信息
- 敏感红线:`.env` / secret / 客户数据不进 commit、issue、PR、截图;`server.md` 仅本地

## 4. 各 issue 专属须知(开工前读你那条)

### #148(Wave 0 地基)—— 单 agent,期间其他人等 rebase

- alembic **一个 revision 全落**(链线性,别留冲突窗口);`pg_trgm` 用 `CREATE EXTENSION IF NOT EXISTS`(docker postgres:16 的 POSTGRES_USER 即 superuser)
- subject 切换顺序:先加 `CurrentUser.subject`(= `user:<users.id>`),再全量 grep `open_id` 逐点改;`permissions.py` 参数名泛化(`user_open_id` → `user_id`,纯命名)
- **`test_v4_permissions.py` 的 hardcode UUID 本来就是 SQL users.id** —— 切 UUID subject 后断言语义不变,是你最好的回归网;跑绿才算完
- 迁移脚本 `scripts/migrate_subjects_to_uuid.py` 输出前后 `list_objects` diff 报告,贴 PR 描述
- department 轴:tuple 不迁、代码只标 `#154 删除` —— **本 issue 别删**(会让 diff 爆炸)
- merge 前在 #155 评论预告(Wave 1 四个分支等着 rebase)

### #149(P1 本地认证)

- 复用 `services/auth.py` 的 `encode_session`;cookie 设置照抄 `routers/auth.py:87-95`
- 依赖加 `argon2-cffi`(不用 passlib,停维护);限流用 `app.state.redis`(per IP + per username)
- auth.py **只加不删**(飞书 OIDC 归 #154);新 event_type 补 `labels.ts` mapping
- 用户名不强制邮箱格式(业务输入:拼音/工号友好)

### #150(P2 管理后台)

- 成员变更直接复用 `permissions.add_user_to_group` / `remove_user_from_group`(`permissions.py:430`,#148 已泛化参数名)
- 禁用 = `revoke_user_completely(user:<uuid>)` + `is_active=false` + audit
- 前端范式照 `AdminAuditPage`;#149 未 merge 前用 `X-User-Id` dev 通道自测(仅 env=dev 生效)
- 不做部门树(ADR-0007 已砍);用户创建时生成临时密码 + `must_change_password=true`(字段 #148 已建)

### #151(标签 + 盲搜)

- **硬验收:搜索结果按 `can_view` 过滤**(`list_objects` 取可达集合),sensitive 素材的存在性(名称/缩略图/计数)一律不得泄露 —— 这是权限体系在本阶段唯一的"主角戏"
- trgm / GIN 索引 #148 已建;百万行查询基准结果贴 PR 描述
- ⌘K 入口 AppHeader 已有;打标 UI 用 AntD `Select mode="tags"`
- 不做 AI 自动标签 / 视频转写(内网 egress 未定,后续迭代)

### #152(生产部署)

- 范围 = ADR-0008 全文;缩略图拆分只动三处:`settings.py` / `workers/main.py` / `services/presign.py`
- **presign host 绑定坑**(S3v4 签 host,`poc/minio/docker-compose.yml:150` 注释):`MINIO_ENDPOINT_PUBLIC` 必须等于浏览器实际访问的 host;内外双入口单值配置不支持
- nginx conf 改动 in-place 写(`cat > file`),不能 `mv`(换 inode → bind mount stale)
- server2 `.env` 是手工真值,deploy 默认不覆盖(仅 `INIT_ENV=1` 重写)
- 飞书 app secret(泄于 `deploy_server2.sh:131` heredoc)处理顺序:**dogfood 过渡期仍用飞书登录** → 先轮换 → sed 进 server2 `.env` → `--force-recreate ms-api`;**#154 cutover 后** → 直接注销飞书应用
- #69 修复时顺手查 `seed_demo_data.py` 同类腐烂

### #153(P3 通知中心)

- `approvals_notify.py` / `invite_notify.py` **只加不删**(IM 删除归 #154;若与 #154 排期重叠,notify 文件归 #154 独占,你先写独立 notifications 模块)
- 轮询即可,不做 WebSocket;SMTP 留空 = no-op 零报错

### #154(P4 飞书下线)

- 按 ADR-0007"下线清单"逐项核对;验收 `grep -ri "open.feishu.cn\|passport.feishu.cn\|lark" material-storage/api material-storage/web` 零残留
- OIDC 抽象**只做一层 provider 配置**(endpoint + client 凭据 + claim 映射,dict 即可,默认空 = 纯本地),不预建多 provider 框架
- `users.feishu_open_id` / `feishu_union_id` 列保留只读,**不删列**

## 5. 协作规则

- **dev 不关 issue**:PR 描述写 `closes #xxx` 或 comment 贴 PR 链接,gatekeeper 复测后关
- 进度同步在 **#155** 下评论(跨 agent 唯一通道是 git + issues)
- merge 顺序:#148 → #149/#150/#151/#152 任意序(各自 rebase)→ #153 → #154
- 本阶段全部完成后,本文件删除
