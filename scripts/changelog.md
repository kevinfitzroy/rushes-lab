# 更新日志

> 以天为单位记一节,二级标题为日期(`## YYYY-MM-DD`),最新的天在最前;每天内用列表记每一项更新,一句话说清 + commit hash 可溯。

## 2026-09-03

- 新增删除文件夹功能(一期:仅空文件夹硬删):后端 `DELETE /api/v1/folders/{id}`(判空 = 无子夹/无文件[含软删],OpenFGA tuple 尽力清理,`folder_deleted` audit);前端文件夹 header 对有权限者显示「删除文件夹」按钮,非空禁用并提示;集成测试覆盖空夹删除/非空 409/无权限 403/硬删后同名可立即重建(0bb9853)
- 删除文件夹权限定档:普通夹 `can_upload`(与创建对称,uploader 自主管理目录结构)、sensitive 夹维持 `can_admin`(sensitive 的 can_upload 实为 downloader 级,当删除门槛太宽);前端按钮门控同规则,测试补 uploader 可删 / sensitive 例外两例
- 设计决策记录:文件夹删除不做软删 —— 空夹软删无收益且 `uq_folder_project_prefix` 全量唯一约束会让同名重建撞 409;非空删除二期方案(软删 + partial unique index)已写入 ROADMAP D iter2

## 2026-08-31

- 内网 dev 环境部署 liuqi 分支(b2054a7):deploy_lan.sh 增强 —— SSH 反向隧道抖动重试(ssh_r 包装,8×6s)、无 rsync 环境的 tar 流兜底(Git Bash 可跑)、目标机 sudo 缺省时自动降级为普通同步;前端 SPA 本地构建后单独同步(rsync 范围排除 static/web)
- PR #176 review 修复:① 重复 tuple 判定收敛为 `is_already_exists_error()`(SDK 异常类型 + 稳定子串,替代易随版本漂移的报错文案匹配;OpenFGA 镜像同步按 digest 固定);② 标签盲搜对 public 项目非敏感 folder 放开(消「列表看得到、盲搜搜不到」断层,敏感目录零泄露不变);③ `roles`/`levels` 参数先校验数组类型(误传字符串不再报费解文案);④ dev 未登录跳转补回 `next` 参数(登录后回跳原页);⑤ `set_password.py` 死 import 清理、local_up.sh 镜像源口径说明对齐
- 审批申请体验修复三连:① 有效期 Segmented 选中态全局加深(墨底白字,统一修掉所有 Segmented "看不出选了哪个"的问题);② 修「自定义」有效期点了没反应的 bug(默认秒数与预设重合导致弹回,现显式记录模式,自定义输入框正常弹出);③ 重复申请防护 —— 已拥有目标权限或已有同目标待审申请时提交会被明确拒绝(400 + 文案)
- 审批列表信息补全:每行显示**申请人姓名**,资源名可点击直接跳转到所在位置(后端列表接口补充 requester_name / folder_id)
- 审批入口可发现性修复:文件详情面板对无下载权限的用户显示「申请下载」按钮,点「下载」被 403 拒绝时自动弹出权限申请(原先只有报错没有入口);审批页提示语从指向不存在的「申请权限」按钮改为描述真实流程;「分享给飞书」按钮更名「分享」(飞书残留);清理 pytest 遗留的 12 条测试审批数据
- folder 授权(grant)面板与邀请面板同款优化:权限改为多选 toggle chips(选中=色块填充+勾号+描边),一次勾选多个 level 批量授予;后端 `POST /folders/{id}/grants` 接受 `levels` 数组(旧单 `level` 兼容)+ 重复授予幂等(原先重复 grant 同 level 会 500)
- 项目邀请面板重做:角色改为多选 toggle chips(选中=色块填充+勾号+描边,一眼可辨),支持一次勾选多个角色批量授予,不再逐个反复邀请;后端 `POST /projects/{id}/members` 接受 `roles` 数组(旧单 `role` 字段兼容),重复授予改幂等(原先重复邀请同角色会 500)

- agent 长期上下文维持 `CLAUDE.md` 为正本(尊重文件历史);新增极简 `AGENTS.md` 指针引用它,作 ZCode / Codex 等跨代理入口
- 本地开发全面切换账号密码登录:dev 与生产同链路(`/login` + session cookie,不再依赖 dev-login 通道),利于实测不同账号/角色;测试账号 alice / bob / evan / outsider 由 `local_up.sh` 自动设好固定 dev 密码(3c51b0c)
- 新增 `api/scripts/set_password.py`:给任意用户设密码 / 登录名;支持 `--list` 核对账号、`--must-change` 测首登强制改密、省略 `--password` 生成一次性临时密码(3c51b0c)
- 修:栈重建后浏览器残留的旧 session cookie 造成 401 循环弹回登录页 —— dev 模式下无效 session 自动回落 `X-User-Id`,生产行为不变(3c51b0c)
- 修:`seed_demo_data` 重跑把 outsider 升成 org admin 的权限泄漏(负向测试账号曾拿到全库可见性);已修查询并清理历史脏 tuple(3c51b0c)
- 前端操作按钮按权限禁用/隐藏:上传、打标、批量删除、新建目录不再"点了选完文件才 403"(d677b1a)
- 公开项目语义补齐:非敏感内容对组织内可浏览,消「看得到目录树、看不到内容」断层;下载仍走申请流,敏感目录仍邀请制(4d8e06b)

## 2026-08-28

- 新增 `api/scripts/local_up.sh`:一条命令完成本地 Docker 全栈部署(依赖栈 → OpenFGA store/model → 生成 `.env` → 构建启动 → 迁移 → seed),幂等可重跑(f5acec0)
- 修 vite dev 的 `/ms-static` 代理劫持 SPA 路由,导致 dev-login 页面打不开的问题(f5acec0)
- Dockerfile 的 apt / pip 镜像源抽成 build arg(默认清华源不变;对清华源包文件 403 的网络可切阿里云)(f5acec0)
- Windows + Docker Desktop 全栈部署验证通过,容器集成测试全绿
