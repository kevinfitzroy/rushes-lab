/**
 * FolderInvitePanel — sensitive folder 邀请管理 (D iter3)。
 * 列当前 invited members + 邀请 modal(UserPicker + level + duration)+ 撤销。
 *
 * 当 active folder 是 sensitive 且选 0 个 asset 时,右栏 AssetSummaryPanel 切到这里。
 */
import { App, Button, Modal, Popconfirm, Select, Skeleton, Tooltip } from 'antd';
import { Building2, Clock, Lock, Plus, Trash2, Users as UsersIcon } from 'lucide-react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import dayjs from 'dayjs';
import 'dayjs/locale/zh-cn';
import relativeTime from 'dayjs/plugin/relativeTime';
import { http } from '../api/client';
import { errorMessage } from '../api/client';
import { useInviteFolder, useRevokeFolder } from '../api/hooks';
import type { Folder, Me } from '../api/types';
import { SubjectPicker, type Subject } from './SubjectPicker';

dayjs.extend(relativeTime);
dayjs.locale('zh-cn');

interface Member {
  subject: string;            // 完整 OpenFGA subject "user:xxx" / "group:xxx#member"
  kind: 'user' | 'group' | 'department';
  subject_id: string;
  name: string;
  level: 'viewer' | 'downloader';
  permanent: boolean;
  expires_at: string | null;
}

interface Props { folder: Folder; me: Me; }

export function FolderInvitePanel({ folder, me }: Props) {
  const [inviteOpen, setInviteOpen] = useState(false);
  const qc = useQueryClient();
  const { message } = App.useApp();

  const { data: members, isLoading } = useQuery({
    queryKey: ['folder-members', folder.id],
    queryFn: async () => (await http.get<Member[]>(`/api/v1/folders/${folder.id}/members`)).data,
    enabled: folder.is_sensitive,
  });

  const revoke = useRevokeFolder();

  return (
    <div>
      {/* header */}
      <div style={{
        padding: '14px 20px 12px',
        borderBottom: '1px solid var(--ms-hairline-soft)',
      }}>
        <div style={{
          fontSize: 10, letterSpacing: '0.08em', textTransform: 'uppercase',
          color: 'var(--ms-ink-subtle)', fontFamily: 'var(--ms-font-mono)',
          fontWeight: 500,
        }}>Sensitive · Members</div>
        <div style={{
          marginTop: 6, display: 'flex', alignItems: 'center', gap: 8,
        }}>
          <Lock size={14} strokeWidth={1.8} style={{ color: 'var(--ms-accent)' }} />
          <span style={{
            fontFamily: 'var(--ms-font-display)', fontSize: 15, fontWeight: 500,
            color: 'var(--ms-ink)', flex: 1,
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}>{folder.name}</span>
        </div>
      </div>

      {/* invite button */}
      <div style={{ padding: '12px 16px',
                    borderBottom: '1px solid var(--ms-hairline-soft)' }}>
        <Button
          type="primary"
          icon={<Plus size={14} strokeWidth={2.2} />}
          onClick={() => setInviteOpen(true)}
          block
          style={{ height: 36 }}
        >邀请成员</Button>
      </div>

      {/* member list */}
      <div style={{ padding: '12px 16px' }}>
        <div style={{
          fontSize: 10, letterSpacing: '0.08em', textTransform: 'uppercase',
          color: 'var(--ms-ink-subtle)', fontFamily: 'var(--ms-font-mono)',
          fontWeight: 500, marginBottom: 8,
        }}>当前成员 {members ? `(${members.length})` : ''}</div>

        {isLoading ? (
          <Skeleton active paragraph={{ rows: 3 }} />
        ) : !members || members.length === 0 ? (
          <div style={{
            padding: '24px 12px', textAlign: 'center',
            fontSize: 12.5, color: 'var(--ms-ink-subtle)',
            border: '1px dashed var(--ms-hairline)',
            borderRadius: 'var(--ms-radius-sm)',
          }}>
            还没人被邀请<br/>点击上方"邀请成员"开始
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {members.map(m => (
              <MemberRow
                key={`${m.subject}|${m.level}`}
                member={m}
                onRevoke={async () => {
                  try {
                    await revoke.mutateAsync({
                      folder_id: folder.id,
                      subject: m.subject,
                      level: m.level,
                      permanent: m.permanent,
                    });
                    message.success('已撤销');
                    qc.invalidateQueries({ queryKey: ['folder-members', folder.id] });
                  } catch (e) { message.error(errorMessage(e, '撤销失败')); }
                }}
              />
            ))}
          </div>
        )}
      </div>

      <InviteModal
        open={inviteOpen}
        onClose={() => setInviteOpen(false)}
        folder={folder}
        me={me}
        onSuccess={() => qc.invalidateQueries({ queryKey: ['folder-members', folder.id] })}
      />
    </div>
  );
}

// ─── MemberRow ───────────────────────────────────────────────────────────────
function MemberRow({
  member, onRevoke,
}: { member: Member; onRevoke: () => void }) {
  const KindIcon = member.kind === 'group' ? UsersIcon
    : member.kind === 'department' ? Building2 : null;
  const initial = (member.name || '?').slice(0, 1).toUpperCase();
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 10,
      padding: '8px 10px',
      background: 'var(--ms-canvas)',
      border: '1px solid var(--ms-hairline-soft)',
      borderRadius: 'var(--ms-radius-sm)',
    }}>
      {/* avatar / icon */}
      {member.kind === 'user' ? (
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
        }}>{member.name}</div>
        <div style={{
          marginTop: 2, fontSize: 10.5, color: 'var(--ms-ink-subtle)',
          display: 'flex', alignItems: 'center', gap: 8,
        }}>
          <LevelBadge level={member.level} />
          {member.permanent ? (
            <span>永久</span>
          ) : member.expires_at ? (
            <Tooltip title={`到期 ${dayjs(member.expires_at).format('YYYY-MM-DD HH:mm')}`}>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 3 }}>
                <Clock size={9} strokeWidth={2} />
                {dayjs(member.expires_at).fromNow()}
              </span>
            </Tooltip>
          ) : <span>临时</span>}
        </div>
      </div>

      <Popconfirm
        title="撤销此成员邀请?"
        okText="撤销" okButtonProps={{ danger: true }}
        onConfirm={onRevoke}
      >
        <Tooltip title="撤销">
          <Button type="text" size="small"
                  icon={<Trash2 size={13} strokeWidth={1.8} />}
                  style={{ color: 'var(--ms-ink-muted)' }} />
        </Tooltip>
      </Popconfirm>
    </div>
  );
}

function LevelBadge({ level }: { level: 'viewer' | 'downloader' }) {
  const color = level === 'downloader' ? 'var(--ms-emerald)' : 'var(--ms-ink-muted)';
  const bg = level === 'downloader' ? 'var(--ms-emerald-soft)' : 'var(--ms-hairline-soft)';
  return (
    <span style={{
      padding: '0 5px', fontFamily: 'var(--ms-font-mono)',
      fontSize: 9.5, color, background: bg, borderRadius: 2,
      letterSpacing: '0.02em',
    }}>{level.toUpperCase()}</span>
  );
}

// ─── Invite modal ────────────────────────────────────────────────────────────
const DUR_OPTIONS = [
  { label: '永久邀请', value: 0 },
  { label: '1 小时', value: 3600 },
  { label: '24 小时', value: 86400 },
  { label: '7 天', value: 7 * 86400 },
  { label: '30 天', value: 30 * 86400 },
];

function InviteModal({
  open, onClose, folder, me, onSuccess,
}: {
  open: boolean; onClose: () => void;
  folder: Folder; me: Me; onSuccess: () => void;
}) {
  const [level, setLevel] = useState<'viewer' | 'downloader'>('viewer');
  const [duration, setDuration] = useState(0);
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const invite = useInviteFolder();
  const { message } = App.useApp();

  const handleSubmit = async () => {
    if (subjects.length === 0) {
      message.warning('请选至少一个主体');
      return;
    }
    let ok = 0, fail = 0;
    for (const s of subjects) {
      try {
        const args: Parameters<typeof invite.mutateAsync>[0] = {
          folder_id: folder.id,
          level,
          duration_seconds: duration > 0 ? duration : undefined,
        };
        if (s.kind === 'user') args.user_open_id = s.id;
        else if (s.kind === 'group') args.group_id = s.id;
        else args.department_id = s.id;
        await invite.mutateAsync(args);
        ok++;
      } catch (e) {
        fail++;
        message.error(`${s.name || s.id}: ${errorMessage(e)}`);
      }
    }
    if (ok > 0) message.success(`邀请成功 ${ok} 个主体${fail > 0 ? ` · 失败 ${fail}` : ''}`);
    setSubjects([]);
    onSuccess();
    onClose();
  };

  return (
    <Modal
      title={`邀请 → ${folder.name}`}
      open={open}
      onCancel={onClose}
      onOk={handleSubmit}
      okText="邀请"
      confirmLoading={invite.isPending}
      destroyOnClose
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16, paddingTop: 4 }}>
        <div>
          <FieldLabel>邀请主体(用户 / 用户组 / 部门)</FieldLabel>
          <SubjectPicker value={subjects} onChange={setSubjects} me={me} />
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <div>
            <FieldLabel>权限等级</FieldLabel>
            <Select
              value={level} onChange={setLevel}
              style={{ width: '100%' }}
              options={[
                { value: 'viewer', label: '查看(viewer)' },
                { value: 'downloader', label: '下载(downloader)' },
              ]}
            />
          </div>
          <div>
            <FieldLabel>有效期</FieldLabel>
            <Select
              value={duration} onChange={setDuration}
              style={{ width: '100%' }}
              options={DUR_OPTIONS}
            />
          </div>
        </div>
        <div style={{
          fontSize: 11.5, color: 'var(--ms-ink-subtle)',
          padding: '10px 12px',
          background: 'var(--ms-accent-faint)',
          border: '1px solid var(--ms-hairline-soft)',
          borderRadius: 'var(--ms-radius-sm)',
        }}>
          <Lock size={10} strokeWidth={2} style={{ verticalAlign: -1, marginRight: 4,
                                                    color: 'var(--ms-accent)' }} />
          被邀请人将能{level === 'downloader' ? '查看 + 下载' : '查看'} <code>{folder.name}</code> 内全部文件。
          {duration > 0 && ' 到期自动失效。'}
        </div>
      </div>
    </Modal>
  );
}

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      fontSize: 11, color: 'var(--ms-ink-muted)',
      marginBottom: 6, fontWeight: 500,
    }}>{children}</div>
  );
}
