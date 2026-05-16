/**
 * 任务中心抽屉 — Tabs 显示上传 / 下载所有任务,带进度条 + 取消 + 移除。
 */
import { Button, Drawer, Empty, List, Progress, Space, Tabs, Tag, Tooltip, Typography } from 'antd';
import { CloseOutlined, DeleteOutlined, FileOutlined, FolderOutlined } from '@ant-design/icons';
import { useUpload } from '../lib/upload-store';
import { useDownloads, type DownloadTask } from '../lib/download-store';

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}
function fmtSpeed(bps: number): string {
  return `${fmtBytes(bps)}/s`;
}

const STATUS_TAG: Record<string, { color: string; text: string }> = {
  pending: { color: 'default', text: '等待' },
  running: { color: 'blue', text: '进行中' },
  success: { color: 'green', text: '完成' },
  failed: { color: 'red', text: '失败' },
  cancelled: { color: 'default', text: '已取消' },
};

interface Props {
  open: boolean;
  onClose: () => void;
}

function UploadList() {
  const { getAllUppies, open, version } = useUpload();

  // 把所有 uppy 实例的所有 files 平铺出来
  const items: { folderId: string; file: { id: string; name: string; size?: number; progress?: { uploadComplete?: boolean; bytesUploaded?: number; bytesTotal?: number; percentage?: number }; error?: unknown } }[] = [];
  for (const [folderId, u] of getAllUppies()) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const files = (u as any).getFiles();
    for (const file of files) items.push({ folderId, file });
  }
  // version dep keeps lint happy:
  void version;

  if (items.length === 0) return <Empty description="无上传任务" style={{ marginTop: 60 }} />;

  return (
    <List
      dataSource={items}
      renderItem={({ folderId, file }) => {
        const pct = file.progress?.percentage ?? 0;
        const complete = !!file.progress?.uploadComplete;
        const failed = !!file.error;
        const status = failed ? 'failed' : complete ? 'success' : pct > 0 ? 'running' : 'pending';
        const tag = STATUS_TAG[status];
        const loaded = file.progress?.bytesUploaded ?? 0;
        const total = file.progress?.bytesTotal ?? file.size ?? 0;

        return (
          <List.Item
            actions={[
              !complete && !failed && (
                <Button key="open" size="small" type="link"
                        onClick={() => open(folderId)}>查看</Button>
              ),
            ].filter(Boolean) as React.ReactNode[]}
          >
            <List.Item.Meta
              avatar={<FolderOutlined />}
              title={
                <Space>
                  <Typography.Text ellipsis style={{ maxWidth: 280 }}>{file.name}</Typography.Text>
                  <Tag color={tag.color}>{tag.text}</Tag>
                </Space>
              }
              description={
                <div>
                  <Progress percent={Math.round(pct)} size="small"
                            status={failed ? 'exception' : complete ? 'success' : 'active'}
                            showInfo={false} />
                  <Space size="middle" style={{ fontSize: 12, color: '#999' }}>
                    <span>{fmtBytes(loaded)} / {fmtBytes(total)}</span>
                    <span>folder · <code>{folderId.slice(0, 8)}…</code></span>
                  </Space>
                </div>
              }
            />
          </List.Item>
        );
      }}
    />
  );
}

function DownloadList() {
  const { tasks, cancel, remove } = useDownloads();
  if (tasks.length === 0) return <Empty description="无下载任务" style={{ marginTop: 60 }} />;

  return (
    <List
      dataSource={tasks}
      renderItem={(t: DownloadTask) => {
        const tag = STATUS_TAG[t.status];
        const pct = t.total > 0 ? Math.round((t.loaded / t.total) * 100) : 0;
        const finalProgress = t.status === 'success' ? 'success' : t.status === 'failed' ? 'exception' : 'active';
        return (
          <List.Item
            actions={[
              t.status === 'running' && (
                <Tooltip title="取消下载" key="cancel">
                  <Button size="small" type="text" icon={<CloseOutlined />} onClick={() => cancel(t.id)} />
                </Tooltip>
              ),
              t.status !== 'running' && (
                <Tooltip title="移除记录" key="remove">
                  <Button size="small" type="text" icon={<DeleteOutlined />} onClick={() => remove(t.id)} />
                </Tooltip>
              ),
            ].filter(Boolean) as React.ReactNode[]}
          >
            <List.Item.Meta
              avatar={<FileOutlined />}
              title={
                <Space>
                  <Typography.Text ellipsis style={{ maxWidth: 280 }}>{t.filename}</Typography.Text>
                  <Tag color={tag.color}>{tag.text}</Tag>
                </Space>
              }
              description={
                <div>
                  <Progress percent={pct} size="small" status={finalProgress} showInfo={false} />
                  <Space size="middle" style={{ fontSize: 12, color: '#999' }}>
                    <span>{fmtBytes(t.loaded)}{t.total ? ` / ${fmtBytes(t.total)}` : ''}</span>
                    {t.status === 'running' && t.speedBps != null && <span>{fmtSpeed(t.speedBps)}</span>}
                    {t.error && <span style={{ color: '#ff4d4f' }}>{t.error}</span>}
                  </Space>
                </div>
              }
            />
          </List.Item>
        );
      }}
    />
  );
}

export function TaskCenterDrawer({ open, onClose }: Props) {
  const { tasks } = useDownloads();
  const { getAllUppies, version } = useUpload();
  void version;

  let uploadCount = 0;
  for (const u of getAllUppies().values()) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    uploadCount += (u as any).getFiles().length;
  }
  const dlCount = tasks.length;

  return (
    <Drawer
      title="任务中心"
      open={open}
      onClose={onClose}
      width="min(560px, 100vw)"
      maskClosable
    >
      <Tabs
        defaultActiveKey="upload"
        items={[
          { key: 'upload', label: `上传 (${uploadCount})`, children: <UploadList /> },
          { key: 'download', label: `下载 (${dlCount})`, children: <DownloadList /> },
        ]}
      />
    </Drawer>
  );
}
