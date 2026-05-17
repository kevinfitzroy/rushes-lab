/**
 * FolderGrantsPanel — 普通(非 sensitive)一级 folder 的 explicit grant 管理。
 * 复用 FolderInvitePanel 形态;三个 level(viewer/downloader/uploader)+ Segmented。
 * 入口:AssetSummaryPanel 在 0 选 + folder 是一级普通 folder 时切到这里。
 */
import { App, Button, Modal, Popconfirm, Segmented, Skeleton, Tooltip } from 'antd';
import { Building2, Folder as FolderIcon, Plus, Trash2, Users as UsersIcon } from 'lucide-react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { http, errorMessage } from '../api/client';
import type { Folder, Me } from '../api/types';
import { SubjectPicker, type Subject } from './SubjectPicker';

type GrantLevel = 'viewer' | 'downloader' | 'uploader';

interface Grant {
  subject: string;
  kind: 'user' | 'group' | 'department';
  subject_id: string;
  name: string;
  level: GrantLevel;
}

const LEVEL_META: Record<GrantLevel, { label: string; color: string; bg: string; desc: string }> = {
  viewer:     { label: '查看', color: 'var(--ms-ink-muted)', bg: 'var(--ms-hairline-soft)',
                desc: '可查看本 folder 内的元数据' },
  downloader: { label: '下载', color: 'var(--ms-emerald)', bg: 'var(--ms-emerald-soft)',
                desc: '可查看 + 下载文件' },
  uploader:   { label: '上传', color: 'var(--ms-amber)',   bg: '#FEF3E8',
                desc: '可查看 + 上传 + 创建子文件夹' },
};
const LEVEL_ORDER: GrantLevel[] = ['uploader', 'downloader', 'viewer'];

interface Props { folder: Folder; me: Me; }

export function FolderGrantsPanel({ folder, me }: Props) {
  const [inviteOpen, setInviteOpen] = useState(false);
  const qc = useQueryClient();
  const { message } = App.useApp();

  const { data: grants, isLoading } = useQuery({
    queryKey: ['folder-grants', folder.id],
    queryFn: async () => (await http.get<Grant[]>(`/api/v1/folders/${folder.id}/grants`)).data,
  });

  const remove = async (g: Grant) => {
    try {
      await http.delete(`/api/v1/folders/${folder.id}/grants`, {
        params: { subject: g.subject, level: g.level },
      });
      message.success(`已撤 ${g.name} 的 ${LEVEL_META[g.level].label} 权限`);
      qc.invalidateQueries({ queryKey: ['folder-grants', folder.id] });
    } catch (e) { message.error(errorMessage(e, '撤销失败')); }
  };

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
        }}>Folder · Explicit grants</div>
        <div style={{ marginTop: 6, display: 'flex', alignItems: 'center', gap: 8 }}>
          <FolderIcon size={14} strokeWidth={1.8} style={{ color: 'var(--ms-ink-muted)' }} />
          <span style={{
            fontFamily: 'var(--ms-font-display)', fontSize: 15, fontWeight: 500,
            color: 'var(--ms-ink)', flex: 1,
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}>{folder.name}</span>
        </div>
        <div style={{
          marginTop: 6, fontSize: 11, color: 'var(--ms-ink-subtle)', lineHeight: 1.5,
        }}>
          补充给特定人 / 部门 / 组的 folder 级权限。<br/>
          与项目级权限取并集(子级可超父级);仅一级 folder 可设。
        </div>
      </div>

      <div style={{ padding: '12px 16px',
                    borderBottom: '1px solid var(--ms-hairline-soft)' }}>
        <Button type="primary" icon={<Plus size={14} strokeWidth={2.2} />}
                onClick={() => setInviteOpen(true)} block style={{ height: 36 }}>
          添加 grant
        </Button>
      </div>

      <div style={{ padding: '12px 16px' }}>
        <div style={{
          fontSize: 10, letterSpacing: '0.08em', textTransform: 'uppercase',
          color: 'var(--ms-ink-subtle)', fontFamily: 'var(--ms-font-mono)',
          fontWeight: 500, marginBottom: 8,
        }}>当前 grants {grants ? `(${grants.length})` : ''}</div>

        {isLoading ? <Skeleton active paragraph={{ rows: 3 }} />
         : !grants || grants.length === 0 ? (
          <div style={{
            padding: '24px 12px', textAlign: 'center',
            fontSize: 12.5, color: 'var(--ms-ink-subtle)',
            border: '1px dashed var(--ms-hairline)',
            borderRadius: 'var(--ms-radius-sm)',
          }}>
            还没设置 explicit grant<br/>folder 沿用项目级权限
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {grants.map(g => (
              <GrantRow key={`${g.subject}|${g.level}`} grant={g} onRevoke={() => remove(g)} />
            ))}
          </div>
        )}
      </div>

      <AddGrantModal
        open={inviteOpen}
        onClose={() => setInviteOpen(false)}
        folder={folder} me={me}
        onSuccess={() => qc.invalidateQueries({ queryKey: ['folder-grants', folder.id] })}
      />
    </div>
  );
}

function GrantRow({ grant: g, onRevoke }: { grant: Grant; onRevoke: () => void }) {
  const meta = LEVEL_META[g.level];
  const KindIcon = g.kind === 'group' ? UsersIcon
    : g.kind === 'department' ? Building2 : null;
  const initial = (g.name || '?').slice(0, 1).toUpperCase();
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 10,
      padding: '8px 10px',
      background: 'var(--ms-canvas)',
      border: '1px solid var(--ms-hairline-soft)',
      borderRadius: 'var(--ms-radius-sm)',
    }}>
      {g.kind === 'user' ? (
        <span style={{
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          width: 26, height: 26, flexShrink: 0,
          background: 'var(--ms-ink)', color: 'var(--ms-canvas)',
          borderRadius: '50%',
          fontFamily: 'var(--ms-font-display)', fontSize: 11, fontWeight: 500,
        }}>{initial}</span>
      ) : (
        <span style={{
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          width: 26, height: 26, flexShrink: 0,
          background: 'var(--ms-hairline-soft)', color: 'var(--ms-ink-muted)',
          borderRadius: 'var(--ms-radius-sm)',
        }}>{KindIcon && <KindIcon size={13} strokeWidth={1.7} />}</span>
      )}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          fontSize: 13, color: 'var(--ms-ink)', fontWeight: 500,
          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        }}>{g.name}</div>
        <div style={{ marginTop: 2 }}>
          <span style={{
            padding: '1px 6px', fontSize: 10, fontWeight: 500, letterSpacing: '0.02em',
            color: meta.color, background: meta.bg, borderRadius: 3,
            fontFamily: 'var(--ms-font-mono)',
          }}>{meta.label.toUpperCase()}</span>
        </div>
      </div>
      <Popconfirm title="撤销此 grant?" okText="撤销" okButtonProps={{ danger: true }}
                  onConfirm={onRevoke}>
        <Tooltip title="撤销">
          <Button type="text" size="small"
                  icon={<Trash2 size={13} strokeWidth={1.8} />}
                  style={{ color: 'var(--ms-ink-muted)' }} />
        </Tooltip>
      </Popconfirm>
    </div>
  );
}

function AddGrantModal({
  open, onClose, folder, me, onSuccess,
}: {
  open: boolean; onClose: () => void;
  folder: Folder; me: Me; onSuccess: () => void;
}) {
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [level, setLevel] = useState<GrantLevel>('viewer');
  const [loading, setLoading] = useState(false);
  const { message } = App.useApp();

  const submit = async () => {
    if (subjects.length === 0) {
      message.warning('请选至少一个主体');
      return;
    }
    setLoading(true);
    let ok = 0, fail = 0;
    for (const s of subjects) {
      try {
        const body: Record<string, string> = { level };
        if (s.kind === 'user') body.user_open_id = s.id;
        else if (s.kind === 'group') body.group_id = s.id;
        else body.department_id = s.id;
        await http.post(`/api/v1/folders/${folder.id}/grants`, body);
        ok++;
      } catch (e) {
        fail++;
        message.error(`${s.name || s.id}: ${errorMessage(e)}`);
      }
    }
    setLoading(false);
    if (ok > 0) {
      message.success(`已加 ${ok} 个 ${LEVEL_META[level].label} grant${fail > 0 ? ` · 失败 ${fail}` : ''}`);
      setSubjects([]);
      onSuccess();
      onClose();
    }
  };

  return (
    <Modal title={`添加 grant → ${folder.name}`}
           open={open} onCancel={onClose} onOk={submit}
           okText="添加" confirmLoading={loading} destroyOnClose>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16, paddingTop: 4 }}>
        <div>
          <FieldLabel>主体(用户 / 用户组 / 部门)</FieldLabel>
          <SubjectPicker value={subjects} onChange={setSubjects} me={me} />
        </div>
        <div>
          <FieldLabel>权限</FieldLabel>
          <Segmented
            block value={level}
            onChange={(v) => setLevel(v as GrantLevel)}
            options={LEVEL_ORDER.map(l => ({ label: LEVEL_META[l].label, value: l }))}
          />
          <div style={{
            marginTop: 8, fontSize: 11, color: 'var(--ms-ink-subtle)', lineHeight: 1.6,
          }}>{LEVEL_META[level].desc}</div>
        </div>
      </div>
    </Modal>
  );
}

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ fontSize: 11, color: 'var(--ms-ink-muted)',
                  marginBottom: 6, fontWeight: 500 }}>{children}</div>
  );
}

// Drawer 形式入口(可选;现在直接在 AssetSummaryPanel 内嵌)
export { FolderGrantsPanel as default };
