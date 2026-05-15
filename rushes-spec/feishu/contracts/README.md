# Contracts

接口契约存放目录。每份契约描述一组稳定的对接接口/事件,是 `feishu-integration` 对外暴露 + 上游(`material-storage` 等)依赖的**唯一稳定面**。

## 命名

- 按业务能力分组,一份契约一个文件:`approval.md`、`identity.md`、`notification.md`、`webhook-events.md` 等
- 文件内多版本并存:用 `## v1`、`## v2` 标题分节;旧版本可标记 `deprecated since YYYY-MM-DD`

## 每份契约必含

- **能力描述**(1-2 句话,说明这组接口干什么)
- **版本号** + **变更日志**
- 每个 endpoint:
  - HTTP method + path
  - request body schema(用 JSON 或 表格,带类型 + 是否必填 + 取值范围)
  - response body schema
  - 错误码枚举(每个错误的语义、HTTP 状态码、客户端应如何处理)
- 状态机(如果接口涉及多步流程,如审批)
- **幂等性 / 重试语义**(尤其对 webhook)
- **向后兼容承诺**

## 模板

```markdown
# Contract: <能力名> (v1)

## 能力描述

一段话描述这个契约覆盖什么业务能力。

## 版本

- **当前版本:** v1
- **状态:** draft / accepted / deprecated
- **变更日志:**
  - 2026-MM-DD: initial draft

## Endpoints

### POST /approvals

**用途:** 发起一个审批申请。

**Request:**

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `applicant_open_id` | string | ✓ | 申请人飞书 open_id |
| `approval_type` | enum(`resource_download` / `temp_permission`) | ✓ | 审批类型 |
| `resource_ref` | string | ✓ | 资源标识(下载场景必填) |
| `reason` | string | ✓ | 申请理由,≤ 500 字 |

**Response 200:**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `approval_id` | string | bridge 内部审批 id,后续查询 / 撤销用 |
| `feishu_instance_code` | string | 飞书 instance_code |
| `status` | enum(`pending`) | 初始状态 |

**Errors:**

| HTTP | code | 含义 | 客户端建议 |
| --- | --- | --- | --- |
| 400 | `invalid_applicant` | open_id 不存在或离职 | 检查身份映射 |
| 503 | `feishu_upstream_unavailable` | 飞书 API 暂时不可达 | 退避重试,bridge 内部已有重试 |

## 状态机

```
pending → approved
        → rejected
        → withdrawn
        → expired
```

## 幂等性

- 上游调用 `POST /approvals` 时建议自带 `Idempotency-Key` header,bridge 在同一 key 下 24 小时内返回同一 `approval_id`

## 向后兼容

- 新增字段(request 可选 / response 任意):**允许**,小版本号递增
- 删除字段 / 改类型 / 改语义:**禁止**,必须新开 v2
```

## 决策权 / 变更流程

详见 [`../COLLABORATION.md §2`](../COLLABORATION.md)。
