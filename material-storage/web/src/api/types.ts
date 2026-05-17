/** ms-api Pydantic schemas 镜像(只挑前端用到的字段)。*/

export interface Me {
  id: string;
  open_id: string;
  union_id: string | null;
  name: string;
  email: string | null;
  organization_id: string | null;
  is_active: boolean;
  is_system_admin: boolean;
}

export interface Project {
  id: string;
  code: string;
  name: string;
  description: string | null;
  organization_id: string;
  minio_bucket: string;
  visibility: 'public' | 'private' | 'stealth';
  is_archived: boolean;
  created_at: string;
}

export interface Folder {
  id: string;
  project_id: string;
  parent_folder_id: string | null;
  name: string;
  minio_prefix: string;
  is_sensitive: boolean;
  created_at: string;
}

export interface Asset {
  id: string;
  folder_id: string;
  filename: string;
  minio_bucket: string;
  minio_key: string;
  etag: string | null;
  minio_version_id: string | null;
  size_bytes: number;
  content_type: string | null;
  created_at: string;
  tags?: {
    thumbnail_key?: string;
    thumbnail_width?: number;
    thumbnail_height?: number;
    thumbnail_failed?: string;
    [k: string]: unknown;
  };
}

export type ApprovalStatus = 'pending' | 'approved' | 'rejected' | 'revoked' | 'expired';
export type ApprovalAction = 'download' | 'access';
export type ApprovalTargetType = 'sensitive_folder' | 'asset' | 'project';

export interface Approval {
  id: string;
  applicant_user_id: string;
  target_type: ApprovalTargetType;
  target_id: string;
  action: ApprovalAction;
  duration_seconds: number | null;
  reason: string;
  status: ApprovalStatus;
  feishu_instance_code: string | null;
  approver_user_id: string | null;
  decided_at: string | null;
  decision_note: string | null;
  created_at: string;
}

export interface DownloadLink {
  url: string;
  expires_in: number;
  is_sensitive: boolean;
}

// ─── share(iter3)──────────────────────────────────────────────────────────
export interface ShareCreateOut {
  token: string;
  landing_url: string;
  expires_at: string;
  sent: { open_id: string; message_id?: string; error?: string }[];
}

export interface ShareResolve {
  kind: 'asset' | 'folder';
  target_id: string;
  sharer_name: string | null;
  expires_at: string;
  asset?: { id: string; filename: string; size_bytes: number; content_type: string | null };
  download_url?: string;
  download_expires_in?: number;
  folder?: { id: string; project_id: string; name: string; is_sensitive: boolean };
}
