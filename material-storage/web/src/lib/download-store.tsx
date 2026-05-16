/**
 * 下载任务 store — fetch + ReadableStream 跟踪 progress,统一在任务中心查看。
 *
 * 策略:
 *   - 优先用 File System Access API(showSaveFilePicker)直接 stream 到本地文件,零内存
 *   - fallback 用 Blob 累积(几百 MB 浏览器可接受;GB 级建议用户用 desktop client)
 *   - AbortController 支持取消
 */
import { createContext, useCallback, useContext, useState, type ReactNode } from 'react';

export type DownloadStatus = 'pending' | 'running' | 'success' | 'failed' | 'cancelled';

export interface DownloadTask {
  id: string;
  filename: string;
  url: string;
  startedAt: number;
  status: DownloadStatus;
  loaded: number;
  total: number;
  speedBps?: number;
  error?: string;
  blobUrl?: string;
  abort?: () => void;
}

interface DownloadCtx {
  tasks: DownloadTask[];
  start: (url: string, filename: string) => Promise<string>;  // 返 task id
  cancel: (id: string) => void;
  remove: (id: string) => void;
}

const Ctx = createContext<DownloadCtx | null>(null);

export function useDownloads() {
  const v = useContext(Ctx);
  if (!v) throw new Error('useDownloads 必须在 DownloadProvider 内');
  return v;
}

// File System Access API 检测
function hasFSA(): boolean {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return typeof (window as any).showSaveFilePicker === 'function';
}

export function DownloadProvider({ children }: { children: ReactNode }) {
  const [tasks, setTasks] = useState<DownloadTask[]>([]);

  const patch = useCallback((id: string, p: Partial<DownloadTask>) => {
    setTasks(ts => ts.map(t => t.id === id ? { ...t, ...p } : t));
  }, []);

  const start = useCallback(async (url: string, filename: string): Promise<string> => {
    const id = `dl-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const ctrl = new AbortController();
    const task: DownloadTask = {
      id, filename, url, startedAt: Date.now(),
      status: 'pending', loaded: 0, total: 0,
      abort: () => ctrl.abort(),
    };
    setTasks(ts => [task, ...ts]);

    // 尝试 File System Access API(零内存 stream)
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let fileHandle: any = null;
    if (hasFSA()) {
      try {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        fileHandle = await (window as any).showSaveFilePicker({ suggestedName: filename });
      } catch (e) {
        // user cancel
        patch(id, { status: 'cancelled', error: '用户取消保存' });
        return id;
      }
    }

    try {
      patch(id, { status: 'running' });
      const res = await fetch(url, { signal: ctrl.signal });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const total = parseInt(res.headers.get('content-length') ?? '0', 10);
      patch(id, { total });

      const reader = res.body!.getReader();
      let loaded = 0;
      let lastTick = Date.now();
      let lastLoaded = 0;

      // FSA writable / fallback chunks
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      let writable: any = null;
      const chunks: Uint8Array[] = [];

      if (fileHandle) {
        writable = await fileHandle.createWritable();
      }

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        if (writable) await writable.write(value);
        else chunks.push(value);
        loaded += value.length;

        const now = Date.now();
        if (now - lastTick > 500) {
          const speedBps = ((loaded - lastLoaded) * 1000) / (now - lastTick);
          patch(id, { loaded, speedBps });
          lastTick = now; lastLoaded = loaded;
        }
      }
      patch(id, { loaded });

      if (writable) {
        await writable.close();
        patch(id, { status: 'success' });
      } else {
        const blob = new Blob(chunks as BlobPart[]);
        const blobUrl = URL.createObjectURL(blob);
        patch(id, { status: 'success', blobUrl });
        // 自动 trigger 浏览器保存
        const a = document.createElement('a');
        a.href = blobUrl;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        setTimeout(() => document.body.removeChild(a), 0);
      }
    } catch (e) {
      const err = e as { name?: string; message?: string };
      if (err.name === 'AbortError') patch(id, { status: 'cancelled', error: '已取消' });
      else patch(id, { status: 'failed', error: err.message ?? String(e) });
    }

    return id;
  }, [patch]);

  const cancel = useCallback((id: string) => {
    setTasks(ts => {
      const t = ts.find(x => x.id === id);
      t?.abort?.();
      return ts;
    });
  }, []);

  const remove = useCallback((id: string) => {
    setTasks(ts => {
      const t = ts.find(x => x.id === id);
      if (t?.blobUrl) URL.revokeObjectURL(t.blobUrl);
      return ts.filter(x => x.id !== id);
    });
  }, []);

  return <Ctx.Provider value={{ tasks, start, cancel, remove }}>{children}</Ctx.Provider>;
}
