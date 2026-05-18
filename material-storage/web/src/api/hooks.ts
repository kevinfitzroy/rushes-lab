/** react-query hooks — 包 ms-api endpoints。*/
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { http } from './client';
import type {
  Approval,
  ApprovalAction,
  ApprovalTargetType,
  Asset,
  DownloadLink,
  Folder,
  Me,
  Project,
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
      admin_user_open_id: string;   // 必填:指派项目 admin(可以是自己)
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
      user_open_id?: string;
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
  target_type: 'sensitive_folder' | 'asset' | 'project';
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
      target_type: 'sensitive_folder' | 'asset' | 'project';
      target_id: string;
      allowed_actions: ('access' | 'download')[];
      receiver_open_id?: string;
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
