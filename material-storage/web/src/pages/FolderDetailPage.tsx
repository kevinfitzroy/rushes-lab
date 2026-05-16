import { App, Button, Empty, List, Skeleton, Space, Tag, Tooltip, Typography } from 'antd';
import { CloudDownloadOutlined, KeyOutlined, UploadOutlined } from '@ant-design/icons';
import { useParams } from 'react-router-dom';
import { useState } from 'react';
import { useAssets, useDownloadLink, useFolder } from '../api/hooks';
import { AppBreadcrumb } from '../components/AppBreadcrumb';
import { RequestAccessModal } from '../components/RequestAccessModal';
import { useUpload } from '../lib/upload-store';
import { useDownloads } from '../lib/download-store';
import { errorMessage } from '../api/client';
import type { Asset } from '../api/types';

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
  const upload = useUpload();
  const downloads = useDownloads();
  const [applyAsset, setApplyAsset] = useState<Asset | null>(null);

  const handleDownload = async (a: Asset) => {
    try {
      const link = await dlLink.mutateAsync(a.id);
      // 走任务中心(fetch + progress + 可取消),右下浮按显示
      await downloads.start(link.url, a.filename);
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
        <Button type="primary" icon={<UploadOutlined />}
                onClick={() => folderId && upload.open(folderId)}>
          上传文件
        </Button>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          后台上传:关掉抽屉/换页面不打断,右下浮窗可查进度
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
