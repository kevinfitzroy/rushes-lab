/**
 * 全局上传 store — uppy 实例提升到 App 顶层。
 * - per folderId 一个 uppy(切 folder 各自独立)
 * - 关 drawer 只 hide UI,uppy 在后台继续上传
 * - dynamic import uppy(保持 code splitting,首屏不加载 uppy chunk)
 */
import { App } from 'antd';
import { useQueryClient } from '@tanstack/react-query';
import {
  createContext,
  useCallback,
  useContext,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { apiBase, errorMessage, http } from '../api/client';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type UppyAny = any;

interface UploadCtx {
  activeFolderId: string | null;
  open: (folderId: string) => Promise<void>;
  close: () => void;
  getUppy: (folderId: string) => UppyAny | undefined;
  getAllUppies: () => Map<string, UppyAny>;
  // tick — UI 用来重渲染 floating indicator
  version: number;
}

const Ctx = createContext<UploadCtx | null>(null);

export function useUpload() {
  const v = useContext(Ctx);
  if (!v) throw new Error('useUpload 必须在 UploadProvider 内');
  return v;
}

export function UploadProvider({ children }: { children: ReactNode }) {
  const [activeFolderId, setActiveFolderId] = useState<string | null>(null);
  const uppies = useRef<Map<string, UppyAny>>(new Map());
  const [version, setVersion] = useState(0);
  const { message } = App.useApp();
  const qc = useQueryClient();

  const buildUppy = useCallback(async (folderId: string): Promise<UppyAny> => {
    const [{ default: Uppy }, { default: AwsS3 }, locale] = await Promise.all([
      import('@uppy/core'),
      import('@uppy/aws-s3'),
      import('@uppy/locales/lib/zh_CN').then(m => m.default),
    ]);

    const u: UppyAny = new Uppy({
      locale,
      restrictions: { maxNumberOfFiles: 50, maxFileSize: 5 * 1024 * 1024 * 1024 },
      autoProceed: false,
    }).use(AwsS3, {
      shouldUseMultipart: true,
      getChunkSize: () => 16 * 1024 * 1024,
      listParts: async () => [],

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      createMultipartUpload: async (file: any) => {
        const { data } = await http.post<{ upload_id: string; key: string; bucket: string }>(
          '/api/v1/assets/uploads',
          {
            folder_id: folderId,
            filename: file.name,
            content_type: file.type || 'application/octet-stream',
            size_bytes: file.size ?? 0,
          });
        u.setFileMeta(file.id, { bucket: data.bucket });
        return { uploadId: data.upload_id, key: data.key };
      },

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      signPart: async (file: any, opts: any) => {
        const bucket = file.meta?.bucket ?? 'ms-dev';
        const url = `${apiBase}/api/v1/assets/uploads/${opts.uploadId}/parts/${opts.partNumber}` +
          `?bucket=${encodeURIComponent(bucket)}&key=${encodeURIComponent(opts.key)}`;
        const { data } = await http.get<{ url: string }>(url);
        return { url: data.url, headers: {} };
      },

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      completeMultipartUpload: async (file: any, opts: any) => {
        const bucket = file.meta?.bucket ?? 'ms-dev';
        await http.post(`/api/v1/assets/uploads/${opts.uploadId}/complete`, {
          upload_id: opts.uploadId,
          bucket, key: opts.key, parts: opts.parts,
        });
        return { location: `s3://${bucket}/${opts.key}` };
      },

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      abortMultipartUpload: async (file: any, opts: any) => {
        const bucket = file.meta?.bucket ?? 'ms-dev';
        await http.delete(`/api/v1/assets/uploads/${opts.uploadId}`, {
          params: { bucket, key: opts.key },
        });
      },
    });

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    u.on('upload-success', (file: any) => {
      message.success(`${file?.name ?? ''} 上传成功`);
      qc.invalidateQueries({ queryKey: ['assets', folderId] });
      setVersion(v => v + 1);
    });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    u.on('upload-error', (file: any, err: any) => {
      message.error(`${file?.name ?? ''} 上传失败:${errorMessage(err)}`);
      setVersion(v => v + 1);
    });
    u.on('progress', () => setVersion(v => v + 1));
    u.on('file-added', () => setVersion(v => v + 1));
    u.on('file-removed', () => setVersion(v => v + 1));

    return u;
  }, [message, qc]);

  const open = useCallback(async (folderId: string) => {
    if (!uppies.current.has(folderId)) {
      const u = await buildUppy(folderId);
      uppies.current.set(folderId, u);
    }
    setActiveFolderId(folderId);
  }, [buildUppy]);

  const close = useCallback(() => setActiveFolderId(null), []);
  const getUppy = useCallback((folderId: string) => uppies.current.get(folderId), []);
  const getAllUppies = useCallback(() => uppies.current, []);

  return (
    <Ctx.Provider value={{ activeFolderId, open, close, getUppy, getAllUppies, version }}>
      {children}
    </Ctx.Provider>
  );
}
