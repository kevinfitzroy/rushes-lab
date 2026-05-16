import { App, Button, List, Space, Spin, Tag, Typography } from 'antd';
import { CloudDownloadOutlined, UploadOutlined } from '@ant-design/icons';
import { useParams } from 'react-router-dom';
import { useState } from 'react';
import { useAssets, useDownloadLink, useFolder } from '../api/hooks';
import { UploadDrawer } from '../components/UploadDrawer';

function fmtBytes(n: number) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}

export default function FolderDetailPage() {
  const { folderId } = useParams<{ folderId: string }>();
  const { data: folder } = useFolder(folderId);
  const { data: assets, isLoading } = useAssets(folderId);
  const dlLink = useDownloadLink();
  const { message } = App.useApp();
  const [uploadOpen, setUploadOpen] = useState(false);

  if (isLoading) return <Spin />;

  return (
    <div>
      <Typography.Title level={4}>
        <Space>
          {folder?.name}
          {folder?.is_sensitive && <Tag color="volcano">sensitive</Tag>}
        </Space>
      </Typography.Title>
      <Typography.Text type="secondary" code>{folder?.minio_prefix}</Typography.Text>

      <div style={{ margin: '12px 0' }}>
        <Button type="primary" icon={<UploadOutlined />} onClick={() => setUploadOpen(true)}>
          上传文件
        </Button>
      </div>

      <List
        bordered
        dataSource={assets ?? []}
        locale={{ emptyText: '空文件夹' }}
        renderItem={(a) => (
          <List.Item
            actions={[
              <Button
                key="dl"
                type="link"
                icon={<CloudDownloadOutlined />}
                loading={dlLink.isPending && dlLink.variables === a.id}
                onClick={async () => {
                  try {
                    const link = await dlLink.mutateAsync(a.id);
                    window.open(link.url, '_blank');
                  } catch (e: unknown) {
                    const err = e as { response?: { status?: number; data?: { detail?: string } } };
                    if (err.response?.status === 403) {
                      message.error('无权限下载,可走 /approvals 申请');
                    } else {
                      message.error(`下载失败:${err.response?.data?.detail ?? '未知'}`);
                    }
                  }
                }}
              >
                下载
              </Button>,
            ]}
          >
            <List.Item.Meta
              title={a.filename}
              description={
                <Space>
                  <span>{fmtBytes(a.size_bytes)}</span>
                  <span style={{ color: '#999' }}>{a.content_type ?? '—'}</span>
                  <span style={{ color: '#999' }}>{new Date(a.created_at).toLocaleString()}</span>
                </Space>
              }
            />
          </List.Item>
        )}
      />

      {folderId && <UploadDrawer open={uploadOpen} onClose={() => setUploadOpen(false)} folderId={folderId} />}
    </div>
  );
}
