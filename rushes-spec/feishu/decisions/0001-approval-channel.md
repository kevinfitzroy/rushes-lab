# ADR-0001: 审批通道走飞书原生审批 v4

- **状态:** accepted
- **日期:** 2026-05-15
- **决策者:** feishu agent
- **审阅:** material-storage agent(经 PR)
- **关联:**
  - 调研:[`../research/approval-integration.md`](../research/approval-integration.md)
  - 需求:[`../requirements/from-material-storage.md`](../requirements/from-material-storage.md) MS-FB-001
  - 契约:[`../contracts/approval.md`](../contracts/approval.md)

## 背景

`material-storage` 需要把"资源下载审批"与"临时权限申请"两类工作流挂到企业 IM。前期调研把通道选型从企业微信换到了飞书(见 [`../research/approval-integration.md`](../research/approval-integration.md))。飞书侧再向下有两条可选路径,需要在动手前留一篇决策痕迹,免得后续被反复回滚。

## 决策

`feishu-integration` 走 **飞书原生审批 v4**(`/open-apis/approval/v4/*`)作为审批通道;不走"三方审批实例同步"。

### 配套子决策

1. **审批定义来源**:初期由人在飞书审批后台 `devMode=on` 配置模板,提交 `approval_code` 进配置;迭代稳定后再用 `POST /open-apis/approval/v4/approval` 代码化。
2. **鉴权**:`tenant_access_token`(2h),Redis 中心化缓存 + 分布式锁,实现见调研 §5.2 伪代码;`user_access_token` 仅用于 SSO 流程(MS-FB-004)。
3. **事件订阅 schema**:**v2 schema**(header + event,事件名形如 `approval.approval.instance.approved_v4` / `…rejected_v4` / `…canceled_v4` 等),不订阅旧的 v1 单事件 `approval_instance`。理由:v2 schema 字段更稳定,加密/签名头与 SDK 通用 webhook 处理一致;v1 是历史遗留,字段较杂。**接入实施时若发现飞书后台只能配 v1,以实测为准回滚此子决策,更新本 ADR**。
4. **附件上传**(若审批表单含附件):走 `POST /approval/openapi/v2/file/upload`,**注意是 v2 路径**,与审批接口本身的 v4 路径不同(见调研 §10)。

## 备选方案与拒绝理由

### A. 三方审批实例同步(`/approval/openapi/v2/external/*`)

- 把工作流引擎留在 material-storage 侧,飞书只展示实例与跳转。
- **拒绝**:material-storage 没有也不需要自建审批工作流引擎;选这条等同于先自研工作流再去对接飞书 UI,徒增成本(调研 §2 已对比)。

### B. 仅用飞书机器人 + 卡片回调,不用审批中心

- 用消息卡片自定义"通过/拒绝"按钮,bridge 通过卡片回调收单。
- **拒绝**:缺审批中心原生支持的转交 / 加签 / 撤销 / 审批历史展示;一旦审批人改换或需多级,要在 bridge 内部重新实现工作流。仅适合"轻量内部确认",不适合作为合规材料下载审批的主通道。
- 保留作为**补充能力**(MS-FB-003 消息卡片推送场景使用)。

## 影响

### 对契约的影响

- bridge 暴露的 `POST /approvals` 直接对应飞书 `POST /open-apis/approval/v4/instances` 调用;申请人字段会落到 `open_id`(MS-FB-002 解析后)。
- bridge → upstream 的 webhook 事件由 bridge 在内部把飞书的多个细分事件(approved/rejected/canceled)统一为单一 `approval.status_changed` 推给上游,屏蔽飞书侧的事件分散。
- `expired` 状态飞书原生没有;v1 契约**不实现**,留待后续根据需求决定由 bridge 实现 TTL 还是由 material-storage 自管(契约 §"未实现项"会显式列出)。

### 对实施的影响

- `feishu-integration/` 依赖官方 SDK `lark-oapi`(Python)+ FastAPI + Redis。
- 飞书侧配置项(`app_id` / `app_secret` / `encrypt_key` / `verification_token` / 审批模板 `approval_code`)走环境变量或 vault,**不入仓库**。env 变量名约定在 `feishu-integration/` 实施目录的 `.env.example`(尚未创建)中冻结。

## 风险与待跟踪事项

- 事件 v2 schema 的字段细节在飞书官方文档(SPA 渲染,WebFetch 不可取)与社区 SDK(adamcavendish/larksuite-oapi-sdk-rs 的 `P2ApprovalInstanceCreatedV4` 等)中存在轻微差异,**实施阶段需要在测试服(`rusheslab.taoxiplan.com`)实测落地后回写到 [`../research/approval-integration.md`](../research/approval-integration.md) §6**。
- 飞书审批模板字段(form control id)更新会失效旧实例的字段路径,实施侧用"新模板新 `approval_code`"+ 配置文件版本号管理。

## 已知配置脏点(留痕,不阻塞契约)

- 当前飞书应用后台事件回调地址配的是 `https://rusheslab.taoxiplan.com/api/wecom/callback`,路径里残留 `wecom`(企微遗留)。**实施开始前**需要在飞书开发者后台把它改成 `/api/feishu/callback` 之类、且对应 bridge 实际的路由。这条会作为单独 GitHub issue(`area:feishu` `type:bug`)跟踪。

## 变更日志

- 2026-05-15: 初版,accepted。
