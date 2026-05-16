import { App, Button, Empty, List, Skeleton, Space, Tag, Tooltip, Typography } from 'antd';
import { CloudDownloadOutlined, KeyOutlined, UploadOutlined } from '@ant-design/icons';
import { useParams } from 'react-router-dom';
import { useState } from 'react';
import { useAssets, useDownloadLink, useFolder } from '../api/hooks';
import { UploadDrawer } from '../components/UploadDrawer';
import { AppBreadcrumb } from '../components/AppBreadcrumb';
import { RequestAccessModal } from '../components/RequestAccessModal';
import { errorMessage } from '../api/client';
import type { Asset } from '../api/types';

function fmtBytes(n: number) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}

function triggerDownload(url: string, filename: string) {
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.target = '_blank';
  a.rel = 'noopener';
  document.body.appendChild(a);
  a.click();
  setTimeout(() => document.body.removeChild(a), 0);
}

export default function FolderDetailPage() {
  const { folderId } = useParams<{ folderId: string }>();
  const { data: folder } = useFolder(folderId);
  const { data: assets, isLoading } = useAssets(folderId);
  const dlLink = useDownloadLink();
  const { message } = App.useApp();
  const [uploadOpen, setUploadOpen] = useState(false);
  const [applyAsset, setApplyAsset] = useState<Asset | null>(null);

  const handleDownload = async (a: Asset) => {
    try {
      const link = await dlLink.mutateAsync(a.id);
      triggerDownload(link.url, a.filename);
    } catch (e: unknown) {
      const err = e as { response?: { status?: number } };
      if (err.response?.status === 403) {
        message.warning('无下载权限,自动打开申请...');
        setApplyAsset(a);
      } else {
        message.error(errorMessage(e, '下载失败'));
      }
    }
  };

  return (
    <div>
      <AppBreadcrumb />
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        <Space>
          {folder?.name ?? <Skeleton.Input active size="small" />}
          {folder?.is_sensitive && <Tag color="volcano" icon={<KeyOutlined />}>sensitive</Tag>}
        </Space>
      </Typography.Title>
      <Typography.Paragraph type="secondary" code style={{ fontSize: 12 }}>{folder?.minio_prefix}</Typography.Paragraph>

      <Space style={{ marginBottom: 12 }}>
        <Button type="primary" icon={<UploadOutlined />} onClick={() => setUploadOpen(true)}>
          上传文件
        </Button>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          上传走 16MB part multipart,5GB 上限
        </Typography.Text>
      </Space>

      {isLoading ? (
        <Skeleton active />
      ) : (assets ?? []).length === 0 ? (
        <Empty description="空文件夹 — 点上传文件添加内容" />
      ) : (
        <List
          bordered
          dataSource={assets!}
          renderItem={(a) => (
            <List.Item
              actions={[
                <Tooltip title="拿 presigned URL 直下" key="dl">
                  <Button type="link" icon={<CloudDownloadOutlined />}
                          loading={dlLink.isPending && dlLink.variables === a.id}
                          onClick={() => handleDownload(a)}>下载</Button>
                </Tooltip>,
              ]}
            >
              <List.Item.Meta
                title={a.filename}
                description={
                  <Space size="middle" style={{ fontSize: 12, color: '#999' }}>
                    <span>{fmtBytes(a.size_bytes)}</span>
                    <span>{a.content_type ?? '—'}</span>
                    <span>{new Date(a.created_at).toLocaleString()}</span>
                  </Space>
                }
              />
            </List.Item>
          )}
        />
      )}

      {folderId && <UploadDrawer open={uploadOpen} onClose={() => setUploadOpen(false)} folderId={folderId} />}
      {applyAsset && (
        <RequestAccessModal
          open
          onClose={() => setApplyAsset(null)}
          targetId={applyAsset.id}
          targetName={applyAsset.filename}
          targetType="asset"
          defaultAction="download"
        />
      )}
    </div>
  );
}
