/**
 * 用户可见的后端枚举 → 中文 label 集中映射(#118)。
 *
 * 原则:
 * - 只换"用户在 UI 上肉眼看到"的展示,**不动**底层数据流(契约 / API / CSV / audit details / mono ID)
 * - 缺 key 时直接返回 raw token 不报错 — 兼容后端新增 event_type 没同步加 label 的情况
 * - keep mono 字体不变(advisor 决策:跟现有视觉一致性 > 中文渲染纯净)
 *
 * 后端 event_type 全集来自 `grep event_type= ... | sort -u`(2026-05-18),共 22 种
 */

export const EVENT_TYPE_LABEL: Record<string, string> = {
  access_denied: '访问被拒',
  approval_card_updated: '审批卡片已更新',
  approval_notified: '审批通知已发送',
  approval_state_changed: '审批状态变更',
  approval_submitted: '审批申请已提交',
  asset_deleted: '文件删除',
  download: '下载',
  download_denied: '下载被拒',
  folder_created: '文件夹创建',
  folder_grant_added: '文件夹权限授予',
  folder_grant_removed: '文件夹权限撤销',
  invite_notified: '邀请通知已发送',
  project_created: '项目创建',
  project_member_added: '项目成员添加',
  project_member_removed: '项目成员移除',
  proxy_download: '代理下载',
  sensitive_folder_invited: '敏感目录邀请',
  sensitive_folder_revoked: '敏感目录权限撤销',
  share_link_accessed: '分享链接访问',
  share_link_created: '分享链接创建',
  signed_url_issued: '临时链接签发',
  upload: '上传',
};

export const ACTION_LABEL: Record<string, string> = {
  access: '访问',
  download: '下载',
};

export const TARGET_TYPE_LABEL: Record<string, string> = {
  asset: '文件',
  folder: '文件夹',
  sensitive_folder: '敏感目录',
  project: '项目',
};

/** raw token 缺 mapping 时直接回退 token 本身,避免渲染 undefined */
export const tlabel = (token: string, map: Record<string, string>): string =>
  map[token] || token;
