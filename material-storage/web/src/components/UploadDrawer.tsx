/**
 * 文件上传抽屉 — uppy v4 + Dashboard + AwsS3 multipart。
 * 直接接 ms-api 5-endpoint。
 */
import { Drawer, App } from 'antd';
import { Dashboard } from '@uppy/react';
import Uppy from '@uppy/core';
import AwsS3 from '@uppy/aws-s3';
import { useEffect, useMemo } from 'react';
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

  useEffect(() => {
    const onSuccess = () => {
      message.success('上传成功');
      qc.invalidateQueries({ queryKey: ['assets', folderId] });
    };
    const onError = (_file: unknown, err: { message?: string }) =>
      message.error(`上传失败:${err?.message ?? '未知错误'}`);
    uppy.on('upload-success', onSuccess);
    uppy.on('upload-error', onError);
    return () => {
      uppy.off('upload-success', onSuccess);
      uppy.off('upload-error', onError);
    };
  }, [uppy, message, qc, folderId]);

  return (
    <Drawer title="上传文件" open={open} onClose={onClose} width={720} destroyOnClose>
      <Dashboard uppy={uppy} height={460} showProgressDetails proudlyDisplayPoweredByUppy={false} />
    </Drawer>
  );
}
