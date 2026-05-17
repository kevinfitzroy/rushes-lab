/**
 * 三栏 workspace:左 FolderTree / 中 AssetTable / 右 AssetSummaryPanel,顶 ActionsBar。
 */
import {
  App, Button, Checkbox, Grid, Layout, Modal, Popconfirm, Skeleton,
  Space, Table, Tooltip,
} from 'antd';
import {
  Download, FileText, Folder as FolderIcon, FolderPlus, Key,
  Lock, RotateCw, Trash2, Upload, Users as UsersIcon,
} from 'lucide-react';
import { useNavigate, useParams } from 'react-router-dom';
import { useEffect, useMemo, useState } from 'react';
import {
  useAssets, useDeleteAsset, useDownloadLink,
  useFolder, useFolders, useMe, useProject,
} from '../api/hooks';
import { AppBreadcrumb } from '../components/AppBreadcrumb';
import { FolderTree } from '../components/FolderTree';
import { AssetSummaryPanel } from '../components/AssetSummaryPanel';
import { AssetThumbnail } from '../components/AssetThumbnail';
import { ProjectMembersDrawer } from '../components/ProjectMembersDrawer';
import { RequestAccessModal } from '../components/RequestAccessModal';
import { NewFolderModal } from '../components/NewFolderModal';
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
  const { data: me } = useMe();
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
  const [newFolderMode, setNewFolderMode] = useState<'root' | 'child' | null>(null);
  const [membersOpen, setMembersOpen] = useState(false);

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
        <div style={{
          marginTop: 60, padding: '60px 40px', textAlign: 'center',
          background: 'var(--ms-surface)', border: '1px dashed var(--ms-hairline)',
          borderRadius: 'var(--ms-radius-lg)',
        }}>
          <FolderIcon size={36} strokeWidth={1.3}
                      style={{ color: 'var(--ms-hairline)', marginBottom: 18 }} />
          <div style={{
            fontFamily: 'var(--ms-font-display)', fontSize: 18, fontWeight: 500,
            color: 'var(--ms-ink)', marginBottom: 8,
          }}>本项目还没有文件夹</div>
          <p style={{ margin: 0, fontSize: 13, color: 'var(--ms-ink-muted)',
                      maxWidth: 320, marginInline: 'auto' }}>
            新建一个开始管理素材,或申请加入已有的 sensitive 目录。
          </p>
          <Space style={{ marginTop: 24 }}>
            <Button type="primary" icon={<FolderPlus size={14} strokeWidth={2} />}
                    onClick={() => setNewFolderMode('root')}>
              新建第一个文件夹
            </Button>
            <Button onClick={() => setApplySensitive(true)}
                    icon={<Key size={14} strokeWidth={2} />}>
              申请 sensitive 目录
            </Button>
          </Space>
        </div>
        {applySensitive && (
          <RequestAccessModal
            open onClose={() => setApplySensitive(false)}
            targetId="" targetName="(请输入 folder UUID)"
            targetType="sensitive_folder" defaultAction="access"
          />
        )}
        {newFolderMode && projectId && (
          <NewFolderModal
            open
            onClose={() => setNewFolderMode(null)}
            projectId={projectId}
            onCreated={(fid) => {
              setActiveFolderId(fid);
              navigate(`/projects/${projectId}/folders/${fid}`, { replace: true });
            }}
          />
        )}
      </div>
    );
  }

  // ─── 列定义 ─────────────────────────────────────────────────────────────
  const cols = [
    {
      title: '文件', dataIndex: 'filename', ellipsis: true,
      render: (v: string, a: Asset) => (
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <AssetThumbnail asset={a} />
          <span style={{
            fontWeight: 500, color: 'var(--ms-ink)',
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}>{v}</span>
          {a.content_type && (
            <span style={{
              fontFamily: 'var(--ms-font-mono)', fontSize: 10.5,
              color: 'var(--ms-ink-subtle)',
              padding: '1px 6px',
              background: 'var(--ms-hairline-soft)',
              borderRadius: 3,
              flexShrink: 0,
            }}>{a.content_type.split('/').pop()}</span>
          )}
        </div>
      ),
    },
    {
      title: '大小', dataIndex: 'size_bytes', width: 96,
      render: (n: number) => (
        <span className="ms-mono" style={{ color: 'var(--ms-ink-muted)', fontSize: 12.5 }}>
          {fmtBytes(n)}
        </span>
      ),
      sorter: (a: Asset, b: Asset) => a.size_bytes - b.size_bytes,
    },
    {
      title: '创建', dataIndex: 'created_at', width: 160,
      render: (v: string) => (
        <span style={{ color: 'var(--ms-ink-muted)', fontSize: 12.5 }}>
          {new Date(v).toLocaleString('zh-CN', {
            month: '2-digit', day: '2-digit',
            hour: '2-digit', minute: '2-digit',
          })}
        </span>
      ),
      responsive: ['lg' as const],
      sorter: (a: Asset, b: Asset) => a.created_at.localeCompare(b.created_at),
    },
    {
      title: '', width: 56, fixed: 'right' as const,
      render: (_: unknown, a: Asset) => (
        <Tooltip title="下载">
          <Button type="text" size="small" icon={<Download size={14} strokeWidth={1.8} />}
                  loading={dlLink.isPending && dlLink.variables === a.id}
                  onClick={(e) => { e.stopPropagation(); handleDownload(a); }}
                  style={{ color: 'var(--ms-ink-muted)' }}
          />
        </Tooltip>
      ),
    },
  ];

  const hasSelection = selectedIds.length > 0;

  // mobile 退化:tree drawer + 单栏 file 列表
  // 桌面:三栏 layout
  return (
    <Layout className="ms-enter" style={{
      minHeight: 'calc(100vh - 56px - 80px)',
      background: 'var(--ms-surface)',
      borderRadius: 'var(--ms-radius-lg)',
      overflow: 'hidden',
      boxShadow: 'var(--ms-shadow-sm)',
    }}>
      {/* 左:folder tree */}
      {!isMobile && (
        <Layout.Sider width={260} theme="light" style={{
          background: 'var(--ms-surface)',
          borderRight: '1px solid var(--ms-hairline)',
          overflow: 'auto',
        }}>
          <FolderTree
            folders={folders}
            projectName={project?.name}
            activeFolderId={activeFolderId}
            onSelect={onFolderSelect}
            onCreateRoot={() => setNewFolderMode('root')}
            onCreateChild={() => setNewFolderMode('child')}
          />
        </Layout.Sider>
      )}

      {/* 中:folder header + actions bar + asset table */}
      <Layout.Content style={{
        background: 'var(--ms-surface)',
        display: 'flex', flexDirection: 'column',
      }}>
        {/* folder header — sensitive 标记用 accent dot */}
        <div style={{
          padding: '16px 24px 12px',
          borderBottom: '1px solid var(--ms-hairline-soft)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            {folder?.is_sensitive && (
              <span title="敏感目录" style={{
                display: 'inline-flex', alignItems: 'center', gap: 4,
                padding: '2px 8px',
                background: 'var(--ms-accent-soft)',
                color: 'var(--ms-accent)',
                borderRadius: 3,
                fontSize: 10.5, fontWeight: 500, letterSpacing: '0.02em',
              }}>
                <Lock size={10} strokeWidth={2.2} />
                SENSITIVE
              </span>
            )}
            <span style={{
              fontFamily: 'var(--ms-font-display)',
              fontSize: 18, fontWeight: 500,
              color: 'var(--ms-ink)',
              letterSpacing: '-0.01em',
              flex: 1,
            }}>{folder?.name ?? '—'}</span>
            {project && me && (
              <Button size="small" icon={<UsersIcon size={13} strokeWidth={1.8} />}
                      onClick={() => setMembersOpen(true)}>
                成员
              </Button>
            )}
          </div>
          {folder?.minio_prefix && (
            <div style={{
              marginTop: 4,
              fontFamily: 'var(--ms-font-mono)',
              fontSize: 11,
              color: 'var(--ms-ink-subtle)',
            }}>{folder.minio_prefix}</div>
          )}
        </div>

        {/* actions bar */}
        <div style={{
          padding: '10px 24px',
          borderBottom: '1px solid var(--ms-hairline-soft)',
          display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap',
          background: 'var(--ms-canvas)',
        }}>
          <Checkbox
            indeterminate={hasSelection && selectedIds.length < (assets?.length ?? 0)}
            checked={hasSelection && selectedIds.length === (assets?.length ?? 0) && (assets?.length ?? 0) > 0}
            onChange={(e) => setSelectedIds(e.target.checked ? (assets ?? []).map(a => a.id) : [])}
          />
          <span style={{ fontSize: 12.5, color: 'var(--ms-ink-muted)' }}>
            {hasSelection ? (
              <>已选 <span className="ms-mono" style={{ color: 'var(--ms-accent)', fontWeight: 500 }}>
                {selectedIds.length}</span> / {assets?.length ?? 0}</>
            ) : (
              <>共 <span className="ms-mono">{assets?.length ?? 0}</span> 个文件</>
            )}
          </span>
          <div style={{ flex: 1 }} />
          <Space size={6}>
            <Button type="primary" size="small"
                    icon={<Upload size={13} strokeWidth={2} />}
                    onClick={() => activeFolderId && upload.open(activeFolderId)}>上传</Button>
            <Button size="small" icon={<RotateCw size={13} strokeWidth={2} />}
                    onClick={() => refetch()}>刷新</Button>
            <Button size="small" icon={<Download size={13} strokeWidth={2} />}
                    disabled={!hasSelection} onClick={handleBulkDownload}>
              下载{hasSelection ? ` ${selectedIds.length}` : ''}
            </Button>
            <Popconfirm
              title={`删除 ${selectedIds.length} 个文件?`}
              description="软删除,可由管理员恢复"
              okText="删除" okButtonProps={{ danger: true }}
              disabled={!hasSelection}
              onConfirm={handleBulkDelete}
            >
              <Button size="small" danger icon={<Trash2 size={13} strokeWidth={2} />}
                      disabled={!hasSelection} loading={del.isPending}>
                删除{hasSelection ? ` ${selectedIds.length}` : ''}
              </Button>
            </Popconfirm>
          </Space>
        </div>

        {/* asset table */}
        <div style={{ flex: 1, overflow: 'auto', padding: '0 8px' }}>
          <Table
            dataSource={assets ?? []}
            rowKey="id"
            loading={assetsLoading}
            columns={cols}
            size="middle"
            scroll={{ x: 600 }}
            pagination={{ pageSize: 30, hideOnSinglePage: true }}
            rowSelection={{
              selectedRowKeys: selectedIds,
              onChange: (keys) => setSelectedIds(keys as string[]),
            }}
            onRow={(record) => ({
              onClick: () => {
                setSelectedIds(prev =>
                  prev.includes(record.id) ? prev.filter(x => x !== record.id) : [...prev, record.id]);
              },
              style: { cursor: 'pointer' },
            })}
            locale={{
              emptyText: (
                <div style={{ padding: '60px 16px' }}>
                  <FileText size={32} strokeWidth={1.3}
                            style={{ color: 'var(--ms-hairline)' }} />
                  <div style={{
                    marginTop: 12, fontSize: 13, color: 'var(--ms-ink-muted)',
                  }}>空文件夹 — 上传文件开始</div>
                </div>
              ),
            }}
          />
        </div>
      </Layout.Content>

      {/* 右:summary */}
      {!isMobile && (
        <Layout.Sider width={320} theme="light" style={{
          background: 'var(--ms-surface)',
          borderLeft: '1px solid var(--ms-hairline)',
          overflow: 'auto',
        }}>
          <AssetSummaryPanel selected={selectedAssets} me={me} folder={folder} />
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

      {newFolderMode && projectId && (
        <NewFolderModal
          open
          onClose={() => setNewFolderMode(null)}
          projectId={projectId}
          parentFolderId={newFolderMode === 'child' ? (activeFolderId ?? undefined) : undefined}
          parentName={newFolderMode === 'child' ? folder?.minio_prefix : undefined}
          parentIsSensitive={newFolderMode === 'child' ? folder?.is_sensitive : false}
          onCreated={(fid) => {
            setActiveFolderId(fid);
            navigate(`/projects/${projectId}/folders/${fid}`, { replace: true });
          }}
        />
      )}

      {project && me && (
        <ProjectMembersDrawer
          open={membersOpen}
          onClose={() => setMembersOpen(false)}
          project={project}
          me={me}
        />
      )}
    </Layout>
  );
}
