/**
 * 右下浮动按钮 — 统一显示上传 + 下载 in-flight 任务数。点开任务中心 drawer。
 */
import { FloatButton, Tooltip } from 'antd';
import { CloudSyncOutlined } from '@ant-design/icons';
import { useMemo, useState } from 'react';
import { useUpload } from '../lib/upload-store';
import { useDownloads } from '../lib/download-store';
import { TaskCenterDrawer } from './TaskCenterDrawer';

export function UploadFloatingIndicator() {
  const { getAllUppies, version, activeFolderId } = useUpload();
  const { tasks } = useDownloads();
  const [centerOpen, setCenterOpen] = useState(false);

  const stats = useMemo(() => {
    const all = getAllUppies();
    let upInflight = 0;
    for (const u of all.values()) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const files = (u as any).getFiles() as { progress?: { uploadComplete?: boolean } }[];
      for (const f of files) if (!f.progress?.uploadComplete) upInflight++;
    }
    const dlInflight = tasks.filter(t => t.status === 'pending' || t.status === 'running').length;
    return { upInflight, dlInflight, total: upInflight + dlInflight };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [version, getAllUppies, tasks]);

  if (stats.total === 0 && !centerOpen) return null;
  if (activeFolderId && stats.total === 0) return null;

  return (
    <>
      <Tooltip title={`上传 ${stats.upInflight} · 下载 ${stats.dlInflight} — 点击查看`} placement="left">
        <FloatButton
          icon={<CloudSyncOutlined />}
          badge={{ count: stats.total, color: '#1677ff' }}
          onClick={() => setCenterOpen(true)}
          style={{ right: 24, bottom: 80 }}
        />
      </Tooltip>
      <TaskCenterDrawer open={centerOpen} onClose={() => setCenterOpen(false)} />
    </>
  );
}
