# ADR-0007: 放弃飞书集成,身份体系自建(本地账号 + OIDC 留口)

- **状态:** accepted
- **日期:** 2026-08-09
- **决策者:** user + material-storage agent
- **关联:**
  - 调研:[`../research/identity-source-alternatives.md`](../research/identity-source-alternatives.md)(v0.3,含全部证据与候选分析)
  - 拟 supersede:[ADR-0002](0002-feishu-contacts-as-identity-source.md)(飞书通讯录作身份 SoT)
  - 旁及(随 feishu-integration 日落一并 archival):`feishu/decisions/0001-approval-channel.md`、`feishu/decisions/0002-bridge-as-oidc-provider.md`
  - 权限模型:`../permissions-model-v4.md`(subject 迁移见"影响"节)

## 背景

1. 生产环境确定改为**局域网部署**(2026-08)。飞书集成在内网的受限面已盘点(调研 §1):技术上可行(redirect 允许内网地址、事件有长连接模式),但需要额外工程。
2. **业务输入(2026-08-09,管理层):**
   - 团队日常 IM 是**企业微信**,飞书非日常行为 —— 飞书登录与 IM 卡片不但无价值,反而增加一条办公沟通渠道成本;
   - 离职自动回收闭环**优先级降低**(内网准入 ≈ 物理准入,已离职人员自然失去接触面);
   - 企业微信第三方接入体验差,且官方要求可信域名(不支持 IP、需公网归属验证),纯内网**不可集成** —— IM 集成整体无候选。
3. 至此飞书集成的两大业务价值支柱(调研 §2:离职自动回收、IM 触达)均被业务侧拆除;技术上可行不再构成保留理由。

## 决策

1. **放弃飞书作为身份源、组织架构源与通知渠道。** 飞书 connector 不迁入生产环境;相关代码(下线清单见"影响"节)随迁移下线。
2. **身份体系自建(S1):** 本地账号密码登录 + 应用内用户/组管理后台;组织架构砍掉部门轴,只留本地组(部门树是飞书同步的副产品,非业务刚需;调研 §4-S1)。
3. **保留标准 OIDC client 留口**(authlib 已在依赖中;飞书 OIDC 流程抽象为 provider 配置),未来客户若引入 IdP 可零迁移接入。
4. **OpenFGA subject 全量迁移**:`user:<open_id>` → `user:<UUID>`(users 表 PK 升任),group/department 一并本地化为实施子任务;存量 tuple 用脚本按 open_id→UUID 映射重写(单租户数据量,脚本级;调研 §3.3)。
5. **feishu-integration 项目日落**:不删仓库目录,标记 archival;`rushes-spec/feishu/contracts/` 契约同步废止。此条须经 GitHub issue 知会 feishu agent(双 agent 仅靠 git + issues 通信)。

## 生产初版定位(2026-08-09 补充,业务输入)

- **第一个生产版本的目标是"方便使用、方便检索",不是权限管理。** 盲搜(标签 + 跨 folder 检索)在局域网前提与现有技术栈下可实现(PG `ILIKE`/`pg_trgm` 起步),是初版核心价值,见 ROADMAP 待办"标签 + 盲搜"。
- **v4 权限体系不拆,仅最小使用:** 起步形态可以是全员共用少量 project/folder(甚至单一项目),默认授权从简(如全员 viewer),让大家快速适应产品;三轴 / 邀请制 / 临时授权保留在体系内,随时可启用。
- **高度隐私功能(sensitive folder 邀请制等)保留,早期可不启用** —— 启用时机由业务按真实隐私场景决定,不因"已建好"而提前铺开。

## 候选与拒绝理由(详见调研 §4)

| 候选 | 结论 | 理由 |
| --- | --- | --- |
| S0 坚持飞书(内网长连接方案) | 拒绝 | 业务价值不成立(IM 无人用、离职闭环已降级),保留只剩成本 |
| S1 应用内自建 | **采纳** | 零外部依赖、无新增运维组件;单应用百人级场景的最简路径(调研 §6 社区证据) |
| S2 对接既有 IdP | 保留为留口 | 客户当前无 IdP;若未来有,经 OIDC 留口接入(决策 3) |
| S3 自托管 IdP(Keycloak/Casdoor 等) | 拒绝 | 单应用 + 百人级,运维地板不值(调研 §6) |
| S4 换企业微信 | 拒绝 | 纯内网不可集成(可信域名规则)+ 接入体验差 |
| S5 混合(飞书 connector 可选) | 拒绝 | connector 无人使用,等价于 S1 + 死代码 |

## 影响

### 身份与权限

- OpenFGA **model 无需改动**(identity-agnostic,调研 §3.2);迁移的是 tuple 数据与调用点。
- 存量 tuple 迁移脚本:open_id→UUID 重写;迁移前后用 `tests/test_v4_permissions.py` 等价验证。
- `permissions-model-v4.md` 需修订:§3 subject 字典改本地 ID、§8 飞书事件同步整节删除(或另存 v5 文档,实施时定)。
- `users.feishu_open_id` / `feishu_union_id` 列保留作历史对照(只读),不再参与登录与权限;新用户不再有飞书字段。
- ADR-0002 的 `external_users` 设计自然并入本地账号体系(外部人员 = 普通本地账号 + 组控制)。

### 功能替代

- **登录:** 本地账号密码(强制改密 / 登录限流 / 密码策略);session JWT 机制不变;`X-User-Id` dev 通道不变。
- **用户/组管理:** 应用内管理后台,成员变更直写 tuple(接管原 contact_sync 角色,数据流更简单)。
- **审批/分享通知:** IM 卡片 → 应用内通知中心 + 可选 SMTP;web 内审批入口本就独立于飞书(`routers/approvals.py`)。
- **离职:** 管理员手动禁用 + 审计兜底(业务已接受,调研 §8-2);无自动回收。
- **GroupPicker:** 飞书通讯录实时查询 → 本地组列表。

### 下线清单(实施时逐项核对)

`services/contact_sync.py`、`routers/webhooks.py`(飞书事件入口)、`services/feishu_client.py`、`services/feishu_contact.py`、`services/feishu_cards.py`、`services/feishu_card_handlers.py`、`services/approvals_notify.py` 与 `invite_notify.py` 的 IM 部分、`routers/auth.py` 飞书 OIDC(抽象为 OIDC provider 留口)、`settings.py` 全部 `feishu_*` 配置项、`web/src/lib/feishu.ts`(JSSDK 加载)、各环境 `.env` 飞书凭据。

### 运维与其他

- 内网部署不再有任何公网依赖,可完全离线运行;`FEISHU_IM_ENABLED` 之类的开关随代码下线删除。
- 泄露在公开仓库的老 PoC 飞书 app secret(`deploy_server2.sh` INIT_ENV heredoc)轮换后,飞书应用本身可注销。
- dogfood 环境(server2)需要 cutover 计划:先跑迁移脚本再切本地登录。
- 已知风险(知情接受):无 —— 原"open_id 应用域悬空"尾部风险(调研 §3.3)随去飞书化消除。

## 变更日志

- 2026-08-09:accepted(user ratify;实施 issue:P1 本地认证 / P2 管理后台 / P3 通知替代 / P4 存量迁移+飞书下线,见调研 §7)
- 2026-08-09 晚:补"生产初版定位"节 —— 初版目标 = 易用 + 检索,权限体系最小使用但不拆除,高隐私功能保留可暂缓启用(业务对话输入)
