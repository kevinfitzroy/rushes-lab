/** react-query hooks — 包 ms-api endpoints。*/
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { http } from './client';
import type {
  Approval,
  ApprovalAction,
  ApprovalTargetType,
  Asset,
  DirectoryGroup,
  DirectoryGroupMember,
  DirectoryUser,
  DirectoryUserCreateOut,
  DownloadLink,
  Folder,
  Me,
  Project,
  SearchResult,
  ShareCreateOut,
  ShareResolve,
} from './types';

// ─── auth ──────────────────────────────────────────────────────────────────
export const useMe = () =>
  useQuery({
    queryKey: ['me'],
    queryFn: async () => (await http.get<Me>('/api/v1/auth/me')).data,
    retry: false,
  });

// #149: 本地账号密码登录(成功置 cookie;must_change_password=true 时前端强制改密)
export const useLocalLogin = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: { username: string; password: string }) =>
      (await http.post<{
        status: string;
        user_id: string;
        name: string;
        must_change_password: boolean;
      }>('/api/v1/auth/local/login', body)).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['me'] }),
  });
};

// #149: 修改密码(旧密码 + 新密码;新密码需过服务端策略)
export const useChangePassword = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: { old_password: string; new_password: string }) =>
      (await http.post<{ status: string }>('/api/v1/auth/change-password', body)).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['me'] }),
  });
};

// ─── projects ──────────────────────────────────────────────────────────────
export const useProjects = () =>
  useQuery({
    queryKey: ['projects'],
    queryFn: async () => (await http.get<Project[]>('/api/v1/projects')).data,
  });

export const useProject = (id: string | undefined) =>
  useQuery({
    queryKey: ['project', id],
    queryFn: async () => (await http.get<Project>(`/api/v1/projects/${id}`)).data,
    enabled: !!id,
  });

export const useCreateProject = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: {
      code: string;
      name: string;
      description?: string;
      organization_id?: string;
      minio_bucket: string;
      admin_user_id: string;   // 必填:指派项目 admin(可以是自己;users.id UUID)
    }) => {
      const { organization_id, ...rest } = body;
      const payload = organization_id ? { ...rest, organization_id } : rest;
      return (await http.post<Project>('/api/v1/projects', payload)).data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['projects'] }),
  });
};

// ─── folders ───────────────────────────────────────────────────────────────
export const useCreateFolder = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: {
      project_id: string;
      parent_folder_id?: string;
      name: string;
      is_sensitive?: boolean;
      minio_prefix?: string;
    }) => (await http.post<Folder>('/api/v1/folders', body)).data,
    onSuccess: (_d, vars) => qc.invalidateQueries({ queryKey: ['folders', vars.project_id] }),
  });
};

export const useFolders = (projectId: string | undefined) =>
  useQuery({
    queryKey: ['folders', projectId],
    queryFn: async () =>
      (await http.get<Folder[]>('/api/v1/folders', { params: { project_id: projectId } })).data,
    enabled: !!projectId,
  });

export const useFolder = (folderId: string | undefined) =>
  useQuery({
    queryKey: ['folder', folderId],
    queryFn: async () => (await http.get<Folder>(`/api/v1/folders/${folderId}`)).data,
    enabled: !!folderId,
  });

export const useInviteFolder = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (args: {
      folder_id: string;
      user_id?: string;      // users.id UUID(#148 起)
      group_id?: string;
      department_id?: string;
      level: 'viewer' | 'downloader';
      duration_seconds?: number;
    }) => {
      const { folder_id, ...body } = args;
      await http.post(`/api/v1/folders/${folder_id}/invite`, body);
    },
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['folder', vars.folder_id] });
      qc.invalidateQueries({ queryKey: ['folder-members', vars.folder_id] });
    },
  });
};

export const useRevokeFolder = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (args: {
      folder_id: string;
      subject: string;             // 完整 "user:xxx" / "group:xxx#member"
      level: 'viewer' | 'downloader';
      permanent: boolean;
    }) => {
      await http.delete(`/api/v1/folders/${args.folder_id}/invite`, {
        params: {
          subject: args.subject,
          level: args.level,
          permanent: args.permanent,
        },
      });
    },
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['folder', vars.folder_id] });
      qc.invalidateQueries({ queryKey: ['folder-members', vars.folder_id] });
    },
  });
};

// ─── assets ────────────────────────────────────────────────────────────────
export const useAssets = (folderId: string | undefined) =>
  useQuery({
    queryKey: ['assets', folderId],
    queryFn: async () =>
      (await http.get<Asset[]>('/api/v1/assets', { params: { folder_id: folderId } })).data,
    enabled: !!folderId,
  });

export const useDownloadLink = () =>
  useMutation({
    mutationFn: async (assetId: string) =>
      (await http.post<DownloadLink>(`/api/v1/assets/${assetId}/download-link`, {})).data,
  });

export const useDeleteAsset = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (assetId: string) => {
      await http.delete(`/api/v1/assets/${assetId}`);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['assets'] }),
  });
};

// #151: 跨 folder 盲搜(文件名 / 标签 / 备注;后端已按 can_view 过滤)
export const useSearchAssets = (q: string | null) =>
  useQuery({
    queryKey: ['asset-search', q],
    queryFn: async () =>
      (await http.get<SearchResult[]>('/api/v1/assets/search', { params: { q } })).data,
    enabled: !!q && q.trim().length > 0,
  });

// #151: 写 user_labels / notes(user_labels 显式传空数组 = 清空)
export const useUpdateAssetMeta = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (args: { asset_id: string; user_labels?: string[]; notes?: string }) =>
      (await http.patch<Asset>(`/api/v1/assets/${args.asset_id}/meta`, {
        user_labels: args.user_labels,
        notes: args.notes,
      })).data,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['assets'] });
      qc.invalidateQueries({ queryKey: ['asset-search'] });
    },
  });
};

// ─── approvals ─────────────────────────────────────────────────────────────
export const useApprovals = (scope: 'self' | 'all', status?: string) =>
  useQuery({
    queryKey: ['approvals', scope, status],
    queryFn: async () =>
      (await http.get<Approval[]>('/api/v1/approvals', { params: { scope, status } })).data,
  });

export const useCreateApproval = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: {
      target_type: ApprovalTargetType;
      target_id: string;
      action: ApprovalAction;
      duration_seconds?: number;
      reason: string;
      // #112 PR-2: 来自 request-link 落地页时附带 token,backend enforce
      via_link?: string;
    }) => {
      const { via_link, ...rest } = body;
      const params = via_link ? { via_link } : undefined;
      return (await http.post<Approval>('/api/v1/approvals', rest, { params })).data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['approvals'] }),
  });
};

// ─── request-links (#112) ──────────────────────────────────────────────────
export interface RequestLinkResolve {
  token: string;
  target_type: 'sensitive_folder' | 'asset' | 'project' | 'folder';
  target_id: string;
  target_name: string | null;
  allowed_actions: ('access' | 'download')[];
  expires_at: string;
  inviter_name: string | null;
  receiver_restricted: boolean;
  receiver_match: boolean;
}

export interface RequestLinkCreateOut {
  token: string;
  landing_url: string;
  expires_at: string;
  allowed_actions: string[];
}

export const useCreateRequestLink = () =>
  useMutation({
    mutationFn: async (body: {
      // #129: 加 folder 支持(全链路接通后)
      target_type: 'sensitive_folder' | 'asset' | 'project' | 'folder';
      target_id: string;
      allowed_actions: ('access' | 'download')[];
      receiver_user_id?: string;   // users.id UUID(#148 起)
      ttl_seconds?: number;
    }) => (await http.post<RequestLinkCreateOut>('/api/v1/request-links', body)).data,
  });

export const useResolveRequestLink = (token: string | undefined) =>
  useQuery({
    queryKey: ['request-link', token],
    queryFn: async () =>
      (await http.get<RequestLinkResolve>(`/api/v1/request-links/${token}`)).data,
    enabled: !!token,
    retry: false,
  });

export const useApproveApproval = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (args: { id: string; decision_note?: string }) =>
      (await http.post<Approval>(`/api/v1/approvals/${args.id}/approve`, {
        decision_note: args.decision_note,
      })).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['approvals'] }),
  });
};

export const useRejectApproval = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (args: { id: string; decision_note?: string }) =>
      (await http.post<Approval>(`/api/v1/approvals/${args.id}/reject`, {
        decision_note: args.decision_note,
      })).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['approvals'] }),
  });
};

// ─── share(iter3)──────────────────────────────────────────────────────────
export const useShareAsset = () =>
  useMutation({
    mutationFn: async (args: {
      asset_id: string;
      receive_open_ids: string[];
      message?: string;
      expires_in_seconds: number;
      requires_login?: boolean;
    }) => {
      const { asset_id, ...body } = args;
      return (await http.post<ShareCreateOut>(`/api/v1/share/assets/${asset_id}`, body)).data;
    },
  });

export const useShareFolder = () =>
  useMutation({
    mutationFn: async (args: {
      folder_id: string;
      receive_open_ids: string[];
      message?: string;
      expires_in_seconds: number;
      requires_login?: boolean;
    }) => {
      const { folder_id, ...body } = args;
      return (await http.post<ShareCreateOut>(`/api/v1/share/folders/${folder_id}`, body)).data;
    },
  });

export const useResolveShare = (token: string | undefined) =>
  useQuery({
    queryKey: ['share', token],
    queryFn: async () => (await http.get<ShareResolve>(`/api/v1/share/${token}`)).data,
    enabled: !!token,
    retry: false,
  });

// ─── directory(#150 本地用户/组管理,admin only)────────────────────────────
export const useDirectoryUsers = (params: { q?: string; is_active?: boolean } = {}) =>
  useQuery({
    queryKey: ['directory-users', params],
    queryFn: async () =>
      (await http.get<DirectoryUser[]>('/api/v1/admin/directory/users', { params })).data,
  });

export const useCreateUser = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: { username: string; name: string; email?: string }) =>
      (await http.post<DirectoryUserCreateOut>('/api/v1/admin/directory/users', body)).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['directory-users'] }),
  });
};

export const useDisableUser = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (userId: string) =>
      (await http.post<DirectoryUser>(`/api/v1/admin/directory/users/${userId}/disable`)).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['directory-users'] }),
  });
};

export const useEnableUser = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (userId: string) =>
      (await http.post<DirectoryUser>(`/api/v1/admin/directory/users/${userId}/enable`)).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['directory-users'] }),
  });
};

export const useResetUserPassword = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (userId: string) =>
      (await http.post<{ temporary_password: string }>(
        `/api/v1/admin/directory/users/${userId}/reset-password`,
      )).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['directory-users'] }),
  });
};

export const useDirectoryGroups = (q = '') =>
  useQuery({
    queryKey: ['directory-groups', q],
    queryFn: async () =>
      (await http.get<DirectoryGroup[]>('/api/v1/admin/directory/groups', { params: { q } })).data,
  });

export const useCreateGroup = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: { name: string; description?: string }) =>
      (await http.post<DirectoryGroup>('/api/v1/admin/directory/groups', body)).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['directory-groups'] }),
  });
};

export const useUpdateGroup = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (args: { groupId: string; name?: string; description?: string }) => {
      const { groupId, ...body } = args;
      return (await http.patch<DirectoryGroup>(`/api/v1/admin/directory/groups/${groupId}`, body)).data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['directory-groups'] }),
  });
};

export const useDeleteGroup = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (groupId: string) => {
      await http.delete(`/api/v1/admin/directory/groups/${groupId}`);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['directory-groups'] }),
  });
};

export const useGroupMembers = (groupId: string | undefined) =>
  useQuery({
    queryKey: ['directory-group-members', groupId],
    queryFn: async () =>
      (await http.get<DirectoryGroupMember[]>(
        `/api/v1/admin/directory/groups/${groupId}/members`,
      )).data,
    enabled: !!groupId,
  });

export const useAddGroupMember = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (args: { groupId: string; user_id: string }) =>
      (await http.post<DirectoryGroupMember>(
        `/api/v1/admin/directory/groups/${args.groupId}/members`,
        { user_id: args.user_id },
      )).data,
    onSuccess: (_d, vars) => {
      qc.invalidateQueries({ queryKey: ['directory-group-members', vars.groupId] });
      qc.invalidateQueries({ queryKey: ['directory-groups'] });
    },
  });
};

export const useRemoveGroupMember = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (args: { groupId: string; userId: string }) => {
      await http.delete(`/api/v1/admin/directory/groups/${args.groupId}/members/${args.userId}`);
    },
    onSuccess: (_d, vars) => {
      qc.invalidateQueries({ queryKey: ['directory-group-members', vars.groupId] });
      qc.invalidateQueries({ queryKey: ['directory-groups'] });
    },
  });
};
