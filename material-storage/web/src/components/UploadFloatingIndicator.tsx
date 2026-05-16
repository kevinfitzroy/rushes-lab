/**
 * 右下浮动按钮 — 当后台有进行中的上传时显示;点开重新唤起 drawer。
 * 注意:监听 UploadProvider 的 version,每次 uppy 事件触发 re-render。
 */
import { FloatButton, Progress, Tooltip } from 'antd';
import { CloudUploadOutlined } from '@ant-design/icons';
import { useMemo } from 'react';
import { useUpload } from '../lib/upload-store';

export function UploadFloatingIndicator() {
  const { activeFolderId, open, getAllUppies, version } = useUpload();

  const stats = useMemo(() => {
    const all = getAllUppies();
    let inflightCount = 0, totalBytes = 0, uploadedBytes = 0;
    const folders: { folderId: string; count: number }[] = [];

    for (const [folderId, u] of all) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const files = (u as any).getFiles() as { progress?: { uploadComplete?: boolean; bytesUploaded?: number; bytesTotal?: number } }[];
      let cnt = 0;
      for (const f of files) {
        if (f.progress?.uploadComplete) continue;
        cnt++;
        inflightCount++;
        totalBytes += f.progress?.bytesTotal ?? 0;
        uploadedBytes += f.progress?.bytesUploaded ?? 0;
      }
      if (cnt > 0) folders.push({ folderId, count: cnt });
    }
    return { inflightCount, totalBytes, uploadedBytes, folders };
    // version 让 useMemo 重算
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [version, getAllUppies]);

  // drawer 已开 / 无任务时不显示
  if (activeFolderId || stats.inflightCount === 0) return null;

  const pct = stats.totalBytes > 0 ? Math.round((stats.uploadedBytes / stats.totalBytes) * 100) : 0;

  return (
    <Tooltip title={`${stats.inflightCount} 个文件上传中(${pct}%),点击查看`} placement="left">
      <FloatButton
        icon={<CloudUploadOutlined />}
        badge={{ count: stats.inflightCount, color: '#1677ff' }}
        onClick={() => stats.folders[0] && open(stats.folders[0].folderId)}
        style={{ right: 24, bottom: 80 }}
        description={
          <Progress percent={pct} size="small" showInfo={false}
                    strokeColor="#1677ff" style={{ width: 36, margin: 0 }} />
        }
        shape="square"
      />
    </Tooltip>
  );
}
