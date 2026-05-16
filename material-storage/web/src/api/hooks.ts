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
      organization_id?: string;       // 留空 → 后端自动从 user/default 推
      minio_bucket: string;
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
      user_id?: string;
      group_id?: string;
      duration_seconds?: number;
    }) => {
      const { folder_id, ...body } = args;
      await http.post(`/api/v1/folders/${folder_id}/invite`, body);
    },
    onSuccess: (_data, vars) => qc.invalidateQueries({ queryKey: ['folder', vars.folder_id] }),
  });
};

export const useRevokeFolder = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (args: { folder_id: string; user_id: string; permanent: boolean }) => {
      await http.delete(`/api/v1/folders/${args.folder_id}/invite/user/${args.user_id}`, {
        params: { permanent: args.permanent },
      });
    },
    onSuccess: (_data, vars) => qc.invalidateQueries({ queryKey: ['folder', vars.folder_id] }),
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
    }) => (await http.post<Approval>('/api/v1/approvals', body)).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['approvals'] }),
  });
};

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
