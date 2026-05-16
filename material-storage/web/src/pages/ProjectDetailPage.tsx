/**
 * 三栏 workspace:左 FolderTree / 中 AssetTable / 右 AssetSummaryPanel,顶 ActionsBar。
 */
import {
  App, Button, Checkbox, Empty, Grid, Layout, Modal, Popconfirm, Skeleton,
  Space, Table, Tag, Tooltip, Typography,
} from 'antd';
import {
  CloudDownloadOutlined, DeleteOutlined, KeyOutlined,
  ReloadOutlined, UploadOutlined,
} from '@ant-design/icons';
import { useNavigate, useParams } from 'react-router-dom';
import { useEffect, useMemo, useState } from 'react';
import {
  useAssets, useDeleteAsset, useDownloadLink,
  useFolder, useFolders, useProject,
} from '../api/hooks';
import { AppBreadcrumb } from '../components/AppBreadcrumb';
import { FolderTree } from '../components/FolderTree';
import { AssetSummaryPanel } from '../components/AssetSummaryPanel';
import { RequestAccessModal } from '../components/RequestAccessModal';
import { useUpload } from '../lib/upload-store';
import { useDownloads } from '../lib/download-store';
import { errorMessage } from '../api/client';
import type { Asset } from '../api/types';

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}

export default function ProjectDetailPage() {
  const { projectId, folderId: paramFolderId } = useParams<{ projectId: string; folderId?: string }>();
  const navigate = useNavigate();
  const screens = Grid.useBreakpoint();
  const isMobile = !screens.md;

  const { data: project } = useProject(projectId);
  const { data: folders, isLoading: foldersLoading } = useFolders(projectId);
  const [activeFolderId, setActiveFolderId] = useState<string | null>(paramFolderId ?? null);

  // 选中 folder 默认为 path 参数;无则 = 首个可见 folder
  useEffect(() => {
    if (paramFolderId) {
      setActiveFolderId(paramFolderId);
    } else if (!activeFolderId && folders && folders.length > 0) {
      setActiveFolderId(folders[0].id);
    }
  }, [paramFolderId, folders, activeFolderId]);

  const { data: folder } = useFolder(activeFolderId ?? undefined);
  const { data: assets, isLoading: assetsLoading, refetch } = useAssets(activeFolderId ?? undefined);

  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  useEffect(() => setSelectedIds([]), [activeFolderId]);

  const selectedAssets = useMemo(
    () => (assets ?? []).filter(a => selectedIds.includes(a.id)),
    [assets, selectedIds],
  );

  const upload = useUpload();
  const downloads = useDownloads();
  const dlLink = useDownloadLink();
  const del = useDeleteAsset();
  const { message } = App.useApp();

  const [applyAsset, setApplyAsset] = useState<Asset | null>(null);
  const [applySensitive, setApplySensitive] = useState(false);

  const onFolderSelect = (fid: string) => {
    setActiveFolderId(fid);
    navigate(`/projects/${projectId}/folders/${fid}`, { replace: true });
  };

  const handleDownload = async (a: Asset) => {
    try {
      const link = await dlLink.mutateAsync(a.id);
      await downloads.start(link.url, a.filename);
    } catch (e: unknown) {
      const err = e as { response?: { status?: number } };
      if (err.response?.status === 403) setApplyAsset(a);
      else message.error(errorMessage(e, '下载失败'));
    }
  };

  const handleBulkDownload = async () => {
    for (const a of selectedAssets) await handleDownload(a);
  };

  const handleBulkDelete = async () => {
    let ok = 0, fail = 0;
    for (const a of selectedAssets) {
      try { await del.mutateAsync(a.id); ok++; }
      catch (e) { fail++; message.error(`${a.filename}: ${errorMessage(e)}`); }
    }
    if (ok > 0) message.success(`删除 ${ok} 个文件${fail > 0 ? ` · 失败 ${fail}` : ''}`);
    setSelectedIds([]);
    refetch();
  };

  if (foldersLoading) return <Skeleton active />;

  // 项目没有任何可见 folder
  if (!folders || folders.length === 0) {
    return (
      <div>
        <AppBreadcrumb />
        <Empty description="本项目没有可见 folder(可能 sensitive 待邀请)" style={{ marginTop: 60 }} />
        <div style={{ textAlign: 'center', marginTop: 16 }}>
          <Button onClick={() => setApplySensitive(true)} icon={<KeyOutlined />}>
            申请 sensitive 目录访问
          </Button>
        </div>
        {applySensitive && (
          <RequestAccessModal
            open onClose={() => setApplySensitive(false)}
            targetId="" targetName="(请输入 folder UUID)"
            targetType="sensitive_folder" defaultAction="access"
          />
        )}
      </div>
    );
  }

  // ─── 列定义 ─────────────────────────────────────────────────────────────
  const cols = [
    {
      title: '文件名', dataIndex: 'filename', ellipsis: true,
      render: (v: string) => <Typography.Text strong>{v}</Typography.Text>,
    },
    {
      title: '大小', dataIndex: 'size_bytes', width: 96,
      render: (n: number) => fmtBytes(n),
      sorter: (a: Asset, b: Asset) => a.size_bytes - b.size_bytes,
    },
    {
      title: '类型', dataIndex: 'content_type', width: 140,
      ellipsis: true,
      render: (v: string | null) => v ?? <Tag>未知</Tag>,
      responsive: ['md' as const],
    },
    {
      title: '创建', dataIndex: 'created_at', width: 160,
      render: (v: string) => new Date(v).toLocaleString('zh-CN'),
      responsive: ['lg' as const],
      sorter: (a: Asset, b: Asset) => a.created_at.localeCompare(b.created_at),
    },
    {
      title: '操作', width: 90, fixed: 'right' as const,
      render: (_: unknown, a: Asset) => (
        <Tooltip title="下载">
          <Button type="text" icon={<CloudDownloadOutlined />}
                  loading={dlLink.isPending && dlLink.variables === a.id}
                  onClick={() => handleDownload(a)} />
        </Tooltip>
      ),
    },
  ];

  const hasSelection = selectedIds.length > 0;

  // mobile 退化:tree drawer + 单栏 file 列表
  // 桌面:三栏 layout
  return (
    <Layout style={{ minHeight: 'calc(100vh - 64px - 50px - 24px)', background: '#fff', borderRadius: 6, overflow: 'hidden' }}>
      {/* 左:folder tree */}
      {!isMobile && (
        <Layout.Sider width={260} theme="light" style={{ borderRight: '1px solid #f0f0f0', overflow: 'auto' }}>
          <FolderTree
            folders={folders}
            projectName={project?.name}
            activeFolderId={activeFolderId}
            onSelect={onFolderSelect}
          />
        </Layout.Sider>
      )}

      {/* 中:actions bar + asset table */}
      <Layout.Content style={{ background: '#fff', display: 'flex', flexDirection: 'column' }}>
        {/* actions bar */}
        <div style={{ padding: '8px 16px', borderBottom: '1px solid #f0f0f0', display: 'flex',
                      alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <Checkbox
            indeterminate={hasSelection && selectedIds.length < (assets?.length ?? 0)}
            checked={hasSelection && selectedIds.length === (assets?.length ?? 0) && (assets?.length ?? 0) > 0}
            onChange={(e) => setSelectedIds(e.target.checked ? (assets ?? []).map(a => a.id) : [])}
          >全选</Checkbox>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {hasSelection ? `已选 ${selectedIds.length} / ${assets?.length ?? 0}` : `共 ${assets?.length ?? 0} 个文件`}
          </Typography.Text>
          <div style={{ flex: 1 }} />
          <Space>
            <Button type="primary" size="small" icon={<UploadOutlined />}
                    onClick={() => activeFolderId && upload.open(activeFolderId)}>上传</Button>
            <Button size="small" icon={<ReloadOutlined />} onClick={() => refetch()}>刷新</Button>
            <Button size="small" icon={<CloudDownloadOutlined />}
                    disabled={!hasSelection} onClick={handleBulkDownload}>
              下载 {hasSelection ? `(${selectedIds.length})` : ''}
            </Button>
            <Popconfirm
              title={`删除 ${selectedIds.length} 个文件?`}
              description="软删除,可由管理员恢复"
              okText="删除" okButtonProps={{ danger: true }}
              disabled={!hasSelection}
              onConfirm={handleBulkDelete}
            >
              <Button size="small" danger icon={<DeleteOutlined />}
                      disabled={!hasSelection} loading={del.isPending}>
                删除 {hasSelection ? `(${selectedIds.length})` : ''}
              </Button>
            </Popconfirm>
          </Space>
        </div>

        {/* folder header */}
        <div style={{ padding: '8px 16px', borderBottom: '1px solid #fafafa' }}>
          <Space>
            {folder?.is_sensitive && <Tag color="volcano" icon={<KeyOutlined />}>sensitive</Tag>}
            <Typography.Text>{folder?.name ?? '—'}</Typography.Text>
            <Typography.Text type="secondary" code style={{ fontSize: 11 }}>
              {folder?.minio_prefix ?? ''}
            </Typography.Text>
          </Space>
        </div>

        {/* asset table */}
        <div style={{ flex: 1, overflow: 'auto' }}>
          <Table
            dataSource={assets ?? []}
            rowKey="id"
            loading={assetsLoading}
            columns={cols}
            size="small"
            scroll={{ x: 600 }}
            pagination={{ pageSize: 30, hideOnSinglePage: true }}
            rowSelection={{
              selectedRowKeys: selectedIds,
              onChange: (keys) => setSelectedIds(keys as string[]),
            }}
            onRow={(record) => ({
              onClick: () => {
                // 行点击 toggle select(避免按住 ctrl 才行)
                setSelectedIds(prev =>
                  prev.includes(record.id) ? prev.filter(x => x !== record.id) : [...prev, record.id]);
              },
              style: { cursor: 'pointer' },
            })}
            locale={{ emptyText: <Empty description="空文件夹" /> }}
          />
        </div>
      </Layout.Content>

      {/* 右:summary */}
      {!isMobile && (
        <Layout.Sider width={320} theme="light" style={{ borderLeft: '1px solid #f0f0f0', overflow: 'auto' }}>
          <AssetSummaryPanel selected={selectedAssets} />
        </Layout.Sider>
      )}

      {/* mobile 下:tree 在顶部 collapsible(简化:用 Modal 选 folder)*/}
      {isMobile && (
        <Modal
          title="选择文件夹"
          open={false /* 留 hamburger 触发,iter2 */}
          onCancel={() => undefined}
          footer={null}
        >
          <FolderTree folders={folders} projectName={project?.name}
                      activeFolderId={activeFolderId} onSelect={onFolderSelect} />
        </Modal>
      )}

      {applyAsset && (
        <RequestAccessModal
          open onClose={() => setApplyAsset(null)}
          targetId={applyAsset.id} targetName={applyAsset.filename}
          targetType="asset" defaultAction="download"
        />
      )}
    </Layout>
  );
}
