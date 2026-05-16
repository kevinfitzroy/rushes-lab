/**
 * 文件上传抽屉 — uppy v4 + Dashboard + AwsS3 multipart。
 * 直接接 ms-api 5-endpoint。
 */
import { Drawer, App } from 'antd';
import Uppy from '@uppy/core';
import Dashboard from '@uppy/dashboard';
import AwsS3 from '@uppy/aws-s3';
import { useEffect, useMemo, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { apiBase, http } from '../api/client';

import '@uppy/core/dist/style.min.css';
import '@uppy/dashboard/dist/style.min.css';

interface Props {
  open: boolean;
  onClose: () => void;
  folderId: string;
}

interface CreateUploadResp {
  upload_id: string;
  key: string;
  bucket: string;
}

export function UploadDrawer({ open, onClose, folderId }: Props) {
  const { message } = App.useApp();
  const qc = useQueryClient();
  const mountRef = useRef<HTMLDivElement>(null);

  const uppy = useMemo(() => {
    let lastBucket = 'ms-dev';
    return new Uppy({
      restrictions: { maxNumberOfFiles: 20, maxFileSize: 5 * 1024 * 1024 * 1024 },
      autoProceed: false,
    }).use(AwsS3, {
      shouldUseMultipart: true,
      getChunkSize: () => 16 * 1024 * 1024,

      createMultipartUpload: async (file) => {
        const { data } = await http.post<CreateUploadResp>('/api/v1/assets/uploads', {
          folder_id: folderId,
          filename: file.name,
          content_type: file.type || 'application/octet-stream',
          size_bytes: file.size ?? 0,
        });
        lastBucket = data.bucket;
        return { uploadId: data.upload_id, key: data.key };
      },

      listParts: async () => [], // backend 不支持 resume,空数组让 uppy 走重新上传

      signPart: async (_file, opts) => {
        const url = `${apiBase}/api/v1/assets/uploads/${opts.uploadId}/parts/${opts.partNumber}` +
          `?bucket=${encodeURIComponent(lastBucket)}&key=${encodeURIComponent(opts.key)}`;
        const { data } = await http.get<{ url: string; expires_in: number }>(url);
        return { url: data.url, headers: {} };
      },

      completeMultipartUpload: async (_file, opts) => {
        const { data } = await http.post(`/api/v1/assets/uploads/${opts.uploadId}/complete`, {
          upload_id: opts.uploadId,
          bucket: lastBucket,
          key: opts.key,
          parts: opts.parts,
        });
        return { location: `s3://${lastBucket}/${opts.key}`, etag: (data as { etag?: string }).etag };
      },

      abortMultipartUpload: async (_file, opts) => {
        await http.delete(`/api/v1/assets/uploads/${opts.uploadId}`, {
          params: { bucket: lastBucket, key: opts.key },
        });
      },
    });
  }, [folderId]);

  // 挂载原生 @uppy/dashboard 到 div(避 @uppy/react peer dep 链)
  useEffect(() => {
    if (!open || !mountRef.current) return;
    const plugin = uppy.use(Dashboard, {
      inline: true,
      target: mountRef.current,
      height: 460,
      showProgressDetails: true,
      proudlyDisplayPoweredByUppy: false,
    });
    return () => {
      const dashPlugin = uppy.getPlugin('Dashboard');
      if (dashPlugin) plugin.removePlugin(dashPlugin);
    };
  }, [open, uppy]);

  useEffect(() => {
    const onSuccess = (file: { name?: string } | undefined) => {
      message.success(`上传成功:${file?.name ?? ''}`);
      qc.invalidateQueries({ queryKey: ['assets', folderId] });
    };
    const onError = (_file: unknown, err: { message?: string }) =>
      message.error(`上传失败:${err?.message ?? '未知错误'}`);
    const onComplete = (result: { successful?: unknown[]; failed?: unknown[] }) => {
      const ok = result.successful?.length ?? 0;
      const fail = result.failed?.length ?? 0;
      if (fail === 0 && ok > 0) setTimeout(() => onClose(), 1500);
    };
    uppy.on('upload-success', onSuccess);
    uppy.on('upload-error', onError);
    uppy.on('complete', onComplete);
    return () => {
      uppy.off('upload-success', onSuccess);
      uppy.off('upload-error', onError);
      uppy.off('complete', onComplete);
    };
  }, [uppy, message, qc, folderId, onClose]);

  return (
    <Drawer title="上传文件" open={open} onClose={onClose} width={720} destroyOnClose>
      <div ref={mountRef} />
    </Drawer>
  );
}
