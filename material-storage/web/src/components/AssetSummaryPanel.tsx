/**
 * 右栏 — 选中文件 summary + 快速操作。
 * 0:Empty 自绘 / 1:meta + 快速操作 / N:类型分布 + 批量统计。
 */
import { App, Tag } from 'antd';
import {
  Copy, Download as DownloadIcon, FileText, Files,
  Hash, Share2,
} from 'lucide-react';
import { useState } from 'react';
import type { Asset, Folder, Me } from '../api/types';
import { useDownloadLink } from '../api/hooks';
import { useDownloads } from '../lib/download-store';
import { errorMessage } from '../api/client';
import { ShareModal } from './ShareModal';
import { FolderInvitePanel } from './FolderInvitePanel';
import { FolderGrantsPanel } from './FolderGrantsPanel';

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}

interface Props {
  selected: Asset[];
  me?: Me;
  folder?: Folder;       // active folder — D iter3 用于 sensitive folder 邀请面板切模式
}

export function AssetSummaryPanel({ selected, me, folder }: Props) {
  const [shareOpen, setShareOpen] = useState(false);
  const { message } = App.useApp();
  const dlLink = useDownloadLink();
  const downloads = useDownloads();

  // D iter3:0 选 + sensitive folder + me → FolderInvitePanel
  if (selected.length === 0 && folder && folder.is_sensitive && me) {
    return <FolderInvitePanel folder={folder} me={me} />;
  }
  // polish 1:0 选 + 普通一级 folder + me → FolderGrantsPanel(子级超父级)
  if (selected.length === 0 && folder && !folder.is_sensitive
      && folder.parent_folder_id === null && me) {
    return <FolderGrantsPanel folder={folder} me={me} />;
  }

  if (selected.length === 0) {
    return (
      <div style={{
        padding: '60px 20px', textAlign: 'center',
      }}>
        <svg width="40" height="40" viewBox="0 0 40 40" style={{ marginBottom: 16 }}>
          <rect x="6" y="10" width="22" height="26" rx="2"
                fill="none" stroke="var(--ms-hairline)" strokeWidth="1.5" />
          <rect x="14" y="4" width="22" height="26" rx="2"
                fill="none" stroke="var(--ms-ink-subtle)" strokeWidth="1.5" />
        </svg>
        <div style={{
          fontSize: 12.5, color: 'var(--ms-ink-muted)', lineHeight: 1.6,
        }}>
          选中文件后<br/>查看详情和快速操作
        </div>
      </div>
    );
  }

  // ─── 单选 ─────────────────────────────────────────────────────────────────
  if (selected.length === 1) {
    const a = selected[0];

    const handleDownload = async () => {
      try {
        const link = await dlLink.mutateAsync(a.id);
        await downloads.start(link.url, a.filename);
      } catch (e) {
        message.error(errorMessage(e, '下载失败'));
      }
    };
    const handleCopyId = async () => {
      try {
        await navigator.clipboard.writeText(a.id);
        message.success('Asset ID 已复制');
      } catch { message.error('复制失败'); }
    };

    return (
      <div>
        {/* Section header */}
        <div style={{
          padding: '14px 20px 10px',
          borderBottom: '1px solid var(--ms-hairline-soft)',
        }}>
          <div style={{
            fontSize: 10, letterSpacing: '0.08em', textTransform: 'uppercase',
            color: 'var(--ms-ink-subtle)', fontFamily: 'var(--ms-font-mono)',
            fontWeight: 500,
          }}>Selected</div>
          <div style={{
            marginTop: 6, display: 'flex', alignItems: 'flex-start', gap: 10,
          }}>
            <span style={{
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
              width: 32, height: 32, flexShrink: 0,
              background: 'var(--ms-hairline-soft)',
              borderRadius: 'var(--ms-radius-sm)',
              color: 'var(--ms-ink-subtle)',
            }}><FileText size={14} strokeWidth={1.5} /></span>
            <div style={{ minWidth: 0, flex: 1 }}>
              <div style={{
                fontFamily: 'var(--ms-font-display)',
                fontSize: 15, fontWeight: 500, lineHeight: 1.3,
                color: 'var(--ms-ink)',
                wordBreak: 'break-word',
              }}>{a.filename}</div>
              <div style={{
                marginTop: 2,
                fontSize: 11.5, color: 'var(--ms-ink-muted)',
              }}>
                <span className="ms-mono">{fmtBytes(a.size_bytes)}</span>
                <span style={{ margin: '0 6px', opacity: 0.4 }}>·</span>
                <span>{new Date(a.created_at).toLocaleDateString('zh-CN')}</span>
              </div>
            </div>
          </div>
        </div>

        {/* Quick actions */}
        <div style={{
          padding: '12px 16px',
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: 4,
          borderBottom: '1px solid var(--ms-hairline-soft)',
        }}>
          <QuickAction icon={<DownloadIcon size={14} strokeWidth={1.8} />}
                       label="下载"
                       loading={dlLink.isPending}
                       onClick={handleDownload} />
          {me && (
            <QuickAction icon={<Share2 size={14} strokeWidth={1.8} />}
                         label="分享给飞书"
                         onClick={() => setShareOpen(true)} />
          )}
          <QuickAction icon={<Copy size={14} strokeWidth={1.8} />}
                       label="复制 ID"
                       onClick={handleCopyId} />
          <QuickAction icon={<Hash size={14} strokeWidth={1.8} />}
                       label="复制 key"
                       onClick={async () => {
                         await navigator.clipboard.writeText(a.minio_key);
                         message.success('MinIO key 已复制');
                       }} />
        </div>

        {/* Meta list */}
        <div style={{ padding: '14px 20px' }}>
          <SectionLabel>详情</SectionLabel>
          <MetaRow label="类型" value={a.content_type ?? <Tag>未知</Tag>} mono={!!a.content_type} />
          <MetaRow label="ID" value={a.id} mono small />
          <MetaRow label="ETag" value={a.etag ? a.etag.slice(0, 16) + '…' : '—'} mono small />
          <MetaRow label="Bucket" value={a.minio_bucket} mono />
          <MetaRow label="Key" value={a.minio_key} mono small breakAll />
          <MetaRow label="Version" value={a.minio_version_id?.slice(0, 16) ?? '—'} mono small />
          <MetaRow label="创建" value={new Date(a.created_at).toLocaleString('zh-CN')} />
        </div>

        {me && (
          <ShareModal
            open={shareOpen}
            onClose={() => setShareOpen(false)}
            target={{ kind: 'asset', id: a.id, label: a.filename }}
            me={me}
          />
        )}
      </div>
    );
  }

  // ─── 多选 ─────────────────────────────────────────────────────────────────
  const totalBytes = selected.reduce((s, a) => s + a.size_bytes, 0);
  const types = new Map<string, number>();
  for (const a of selected) {
    const t = a.content_type ?? '未知';
    types.set(t, (types.get(t) ?? 0) + 1);
  }

  return (
    <div>
      <div style={{
        padding: '14px 20px 12px',
        borderBottom: '1px solid var(--ms-hairline-soft)',
      }}>
        <div style={{
          fontSize: 10, letterSpacing: '0.08em', textTransform: 'uppercase',
          color: 'var(--ms-ink-subtle)', fontFamily: 'var(--ms-font-mono)',
          fontWeight: 500,
        }}>Selection</div>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 6 }}>
          <span style={{
            fontFamily: 'var(--ms-font-display)',
            fontSize: 28, fontWeight: 500,
            color: 'var(--ms-ink)',
          }}>{selected.length}</span>
          <span style={{ fontSize: 12.5, color: 'var(--ms-ink-muted)' }}>个文件</span>
        </div>
        <div style={{
          marginTop: 4, fontSize: 12, color: 'var(--ms-ink-muted)',
        }}>
          总大小 <span className="ms-mono" style={{ color: 'var(--ms-ink)' }}>
            {fmtBytes(totalBytes)}
          </span>
        </div>
      </div>

      <div style={{ padding: '14px 20px' }}>
        <SectionLabel>类型分布</SectionLabel>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {Array.from(types.entries()).map(([t, c]) => (
            <span key={t} style={{
              padding: '4px 10px',
              background: 'var(--ms-hairline-soft)',
              borderRadius: 'var(--ms-radius-sm)',
              fontSize: 11.5,
              color: 'var(--ms-ink-muted)',
            }}>
              <Files size={10} strokeWidth={1.8}
                     style={{ marginRight: 6, verticalAlign: -1 }} />
              <span className="ms-mono">{t.split('/').pop() || t}</span>
              <span style={{ marginLeft: 8, color: 'var(--ms-ink)' }}>×{c}</span>
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── 子组件 ─────────────────────────────────────────────────────────────────
function QuickAction({
  icon, label, onClick, loading,
}: {
  icon: React.ReactNode; label: string;
  onClick: () => void; loading?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={loading}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 8,
        padding: '8px 10px',
        background: 'transparent', border: '1px solid transparent',
        borderRadius: 'var(--ms-radius-sm)',
        color: 'var(--ms-ink)', fontSize: 12.5, fontFamily: 'inherit',
        cursor: loading ? 'wait' : 'pointer',
        opacity: loading ? 0.5 : 1,
        transition: 'all var(--ms-dur-fast) var(--ms-ease)',
      }}
      onMouseEnter={e => {
        if (!loading) {
          e.currentTarget.style.background = 'var(--ms-hairline-soft)';
          e.currentTarget.style.borderColor = 'var(--ms-hairline)';
        }
      }}
      onMouseLeave={e => {
        e.currentTarget.style.background = 'transparent';
        e.currentTarget.style.borderColor = 'transparent';
      }}
    >
      <span style={{ color: 'var(--ms-ink-muted)' }}>{icon}</span>
      <span>{label}</span>
    </button>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      fontSize: 10, letterSpacing: '0.08em', textTransform: 'uppercase',
      color: 'var(--ms-ink-subtle)', fontFamily: 'var(--ms-font-mono)',
      fontWeight: 500, marginBottom: 10,
    }}>{children}</div>
  );
}

function MetaRow({
  label, value, mono, small, breakAll,
}: {
  label: string;
  value: React.ReactNode;
  mono?: boolean;
  small?: boolean;
  breakAll?: boolean;
}) {
  return (
    <div style={{
      display: 'flex', alignItems: 'baseline',
      padding: '6px 0',
      gap: 12,
      borderBottom: '1px solid var(--ms-hairline-soft)',
    }}>
      <span style={{
        flexShrink: 0, width: 56,
        fontSize: 11, color: 'var(--ms-ink-subtle)',
      }}>{label}</span>
      <span style={{
        flex: 1, minWidth: 0,
        fontSize: small ? 11 : 12.5,
        color: 'var(--ms-ink)',
        fontFamily: mono ? 'var(--ms-font-mono)' : undefined,
        wordBreak: breakAll ? 'break-all' : undefined,
        overflow: breakAll ? undefined : 'hidden',
        textOverflow: breakAll ? undefined : 'ellipsis',
        whiteSpace: breakAll ? undefined : 'nowrap',
      }}>{value}</span>
    </div>
  );
}
