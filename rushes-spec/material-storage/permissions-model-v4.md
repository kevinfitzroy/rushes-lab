# material-storage 权限模型 v4

> Status: Active(2026-05-17 起,iter a1 落地)
> 前身:v3 (PoC) → v4 (生产路径,飞书 ID 直作 OpenFGA subject)
> 实现:`material-storage/api/app/services/permissions.py` + `material-storage/poc/openfga/store.fga.yaml`

## 1. 一句话

**OpenFGA ReBAC 作权限 enforcement engine,subject ID 直接复用飞书 ID 体系(user/department/group/organization),日常组织变更管理员只在飞书操作,我们订阅事件自动同步;细粒度授权(项目级 / 一级 folder explicit / sensitive 邀请)在本应用 UI 操作。**

## 2. 核心边界

| 谁来做 | 在哪里做 |
|---|---|
| 身份字典(谁是谁)+ 组织结构(谁在哪个部门/组) | **飞书后台** → 事件订阅同步进 OpenFGA |
| 项目级 / folder 级 / 文件级 access control | **本应用** OpenFGA tuples |
| 业务行为(上传、下载、删除、审批)前的 enforce | **本应用** check OpenFGA |

我们**不**用飞书的"自定义权限"(没这能力)、也**不**把 ACL 元数据塞进飞书云盘(只支持飞书自家文档)。

---

## 3. Subject 字典(谁拥有权限)

> **2026-08-09 修订(ADR-0007 / issue #148)**:subject 已从飞书 ID 全量切换为本地 ID。
> 下表为现行约定;迁移脚本 `scripts/migrate_subjects_to_uuid.py` 负责存量 tuple 重写。

OpenFGA `type user` 的 subject ID 一律用本地 ID:

| OpenFGA type | ID 来源 | 关系 |
|---|---|---|
| `user:<users.id UUID>` | 本地 `users.id`(PG UUID PK;飞书同步来的 user 为 `uuid5(NAMESPACE_DNS, "feishu:user:{open_id}")`) | 叶子 subject |
| `group:<groups.id UUID>` | 本地 `groups.id`(#148 新建 `groups` / `group_memberships` 表;飞书迁移来的组为 `uuid5(NAMESPACE_DNS, "feishu:group:{gid}")`) | `member: [user, department#member]` |
| `department:<dept_id>` | **已废弃(ADR-0007)**:存量 tuple 不迁、保留原样,代码随 #154 / P4 飞书下线一并清理 | `member: [user, department#member]` 自递归 |
| `organization:<tenant_key>` | 飞书 `tenant_key`(整个企业;组织轴保留不变) | `admin/member: [user, group#member, department#member]` |

历史决策记录(原"为什么不用 internal UUID",已被 ADR-0007 推翻):
- ~~飞书事件直接带 `open_id`,转换 UUID 又要查 db,徒增延迟 + 单点~~
- ~~管理员在飞书后台改组织,事件流直接更新 OpenFGA,无需中转~~
- `角色`(functional_role)飞书 OpenAPI 无 list/event,**不引入**;弃飞书后由本地 `groups` 表承担"用户组"语义

---

## 4. Object 与 Relation(谁能对什么做什么)

### 4.1 project

```fga
type project
  relations
    define org: [organization]
    define admin: [user, group#member]
    # 三轴并列
    define viewer:     [user, group#member, department#member]
    define downloader: [user, group#member, department#member]
    define uploader:   [user, group#member, department#member]
    # 时间限定下载 grant(approval download → 实习生 30d / 批量)
    define explicit_downloader: [user with non_expired_grant]
    # 派生
    define can_view:     admin or viewer or downloader or uploader or explicit_downloader
    define can_download: admin or downloader or explicit_downloader
    define can_upload:   admin or uploader
    define can_admin:    admin
```

**典型授权**:
- 创建者自动 `admin`(`POST /projects` bootstrap)
- "默认查看" → `department:<dept>#member` 作 `viewer`(全员可见项目元数据)
- "默认下载" → `group:<editors>#member` 作 `downloader`(剪辑师组可下载)
- "上传/编辑" → `group:<photographers>#member` 作 `uploader`(摄影师组可上传)

### 4.2 folder(普通)

```fga
type folder
  relations
    define parent: [project, folder]              # 任意嵌套
    # 子级 explicit grant — 与父级 union (子级权限可超过父级)
    # 业务层 enforce:仅一级 folder 允许 grant
    define explicit_viewer:     [user, group#member, department#member]
    define explicit_downloader: [user, group#member, department#member]
    define explicit_uploader:   [user, group#member, department#member]
    define can_view:     explicit_viewer or explicit_downloader or explicit_uploader or can_view from parent
    define can_download: explicit_downloader or explicit_uploader or can_download from parent
    define can_upload:   explicit_uploader or can_upload from parent
    define can_admin:    can_admin from parent
```

**子级权限可超父级**:即使 project 没给 user 任何权限,某个一级 folder 给 user explicit_downloader,user 在这个 folder 就能 download(其他 folder 仍无权)。

### 4.3 sensitive_folder(邀请制 — 完全独立)

```fga
type sensitive_folder
  relations
    define parent: [project]                       # 只能直挂 project(限一级)
    define invited_viewer:     [user, group#member, department#member]
    define invited_downloader: [user, group#member, department#member]
    # 时间限定邀请
    define explicit_invited_viewer:     [user with non_expired_grant,
                                          group#member with non_expired_grant,
                                          department#member with non_expired_grant]
    define explicit_invited_downloader: 同上
    define can_view:     invited_viewer or invited_downloader or explicit_invited_viewer or explicit_invited_downloader
    define can_download: invited_downloader or explicit_invited_downloader
    define can_admin:    can_admin from parent   # 仅 admin 从 project 继承
    define can_upload:   can_download             # sensitive 上传 = downloader 等级
```

**完全独立**:不从 project 继承 view/download,即使 project admin 之外任何身份都看不到 sensitive folder(除非被显式 invited)。
sensitive folder list 走 OpenFGA `list_objects(can_view, sensitive_folder)`,没权限的 user **`GET /folders` 里根本看不到这个 folder**。

### 4.4 asset

```fga
type asset
  relations
    define parent: [folder, sensitive_folder]
    # 单文件级临时下载(就这一个文件给某人)
    define explicit_downloader: [user with non_expired_grant]
    define can_view:     explicit_downloader or can_view from parent
    define can_download: explicit_downloader or can_download from parent
    define can_upload:   can_upload from parent
    define can_admin:    can_admin from parent
```

---

## 5. 权限蕴含(谁包含谁)

```
admin ⊃ everything
upload ⊃ view + 创建 sub folder
download ⊃ view
view 最弱
```

实现层面:`can_view := admin or viewer or downloader or uploader or explicit_downloader`,任何高于 viewer 的角色自然包含 view。"上传隐含创建 sub folder" 在业务层做(`POST /folders` body parent_folder_id=X 检查 `can_upload on folder:X`)。

## 6. 业务层 enforce(model 之外的硬规则)

| 规则 | enforce 位置 |
|---|---|
| sensitive folder 必须直挂 project | `POST /folders` 拒 parent_folder_id+is_sensitive 同时存在 |
| 仅一级 folder 可 grant explicit_* | `POST /folders/{id}/grant`(D iter 后续)校验 `parent_folder_id IS NULL` |
| 创建 sub folder 需 can_upload on parent | `POST /folders` 检查 `can_upload` |
| 删除 asset 需 can_admin | `DELETE /assets/{id}` 检查 |
| sensitive folder 邀请仅 admin 操作 | `POST /folders/{id}/invite` 检查 `can_admin` |

## 7. 默认授权范式(创建项目时)

PoC 自动 + D iter3 UI 配置:

```
新建 project:
  admin       = 创建者(user)
  viewer      = 选 0+ department / 0+ group(默认 "组织全员" 部门)
  downloader  = 选 0+ group  (默认空)
  uploader    = 选 0+ group  (默认空,慎给)
```

子目录无需配置,默认从 project 继承;特定子目录想加权限 → 在一级 folder 上 explicit grant。深 folder 想要不同权限 → 拆成新一级 folder。

---

## 8. 飞书事件同步

> **(#154 / ADR-0007 已删除)** — 本节描述的飞书事件流同步已随飞书集成整体下线;
> 存量 department tuples 原样保留(不迁),但无任何代码再写入。

## 9. 典型场景 e2e(对照 fga test)

(以 `store.fga.yaml` tests 段为 source of truth — `fga model test` 跑 36/36 pass)

| 场景 | 期望 |
|---|---|
| Alice org admin → project | full access ✓ |
| Evan in editing dept + editors group → project viewer + downloader | can_view ✓ can_download ✓ can_upload ✗ |
| Evan invited_viewer 进 sensitive folder | can_view ✓ can_download ✗ |
| Mia in motion_design (子部门) → 自动 editing member → project viewer | can_view ✓ |
| Mia explicit_invited_downloader sensitive(24h)+ 19h 时刻 check | can_download ✓ |
| Mia 同上 + 25h 时刻 check(过期) | can_view ✗ can_download ✗ |
| Outsider 完全无 tuple → project / sensitive folder | all ✗ |

## 10. 不在 v4 范围(可能 v5+)

- **role 类型 subject**(飞书 functional_role 无 list/event → 现在跳过,用 group 替代)
- **sensitive_folder 嵌套 sensitive**(产品复杂度高,先限平铺)
- **deep folder explicit grant**(同上,产品上"开新一级 folder"已替代)
- **asset 级临时上传 grant**(没需求,download 有就够)
- **跨 tenant 权限**(单 tenant PoC 先做,SaaS 化时加 tenant 前缀)

## 11. 参考代码 / 入口

- Model:`material-storage/poc/openfga/store.fga.yaml`
- Service:`material-storage/api/app/services/permissions.py`(`PermissionsService` + `fmt_subject()` helper)
- Tests:`material-storage/api/tests/test_permissions_v4.py`(a1 iter 加)
- Seed:`material-storage/api/scripts/seed_demo_data.py`
- 飞书事件 handler:`material-storage/api/app/routers/webhooks.py`(a2 iter 实施)

---

## 修订记录

- **2026-08-09(ADR-0007 / issue #148)**:OpenFGA subject 从飞书 ID 全量迁移到本地 ID
  —— `user:<open_id>` → `user:<users.id UUID>`;group 从飞书 gid 迁到本地 `groups.id`
  UUID(新表 `groups` / `group_memberships`);department 轴废弃(存量 tuple 不迁,代码随
  P4 / #154 清理);organization 轴不变。存量 tuple 由
  `material-storage/api/scripts/migrate_subjects_to_uuid.py` 重写;§3 subject 字典已改为
  现行约定,§8 飞书事件同步标注待删除。
