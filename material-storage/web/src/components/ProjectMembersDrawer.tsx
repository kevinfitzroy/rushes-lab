/**
 * ProjectMembersDrawer — 项目成员管理(D iter4)。
 * 入口:ProjectDetailPage 顶栏"成员"按钮。
 *
 * 成员卡片:头像/icon + name + roles 徽章串 + per-role 撤销 + 邀请按钮。
 * 邀请 Modal:UserPicker + role segmented control(admin/uploader/downloader/viewer)。
 */
import { App, Button, Drawer, Modal, Popconfirm, Segmented, Skeleton, Tooltip } from 'antd';
import { Building2, Plus, ShieldCheck, Trash2, Users as UsersIcon } from 'lucide-react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { http, errorMessage } from '../api/client';
import type { Me, Project } from '../api/types';
import { SubjectPicker, type Subject } from './SubjectPicker';

type ProjectRole = 'admin' | 'uploader' | 'downloader' | 'viewer';

interface Member {
  subject: string;
  kind: 'user' | 'group' | 'department';
  subject_id: string;
  name: string;
  roles: ProjectRole[];
}

const ROLE_META: Record<ProjectRole, { label: string; color: string; bg: string }> = {
  admin:      { label: '管理', color: 'var(--ms-accent)',  bg: 'var(--ms-accent-soft)' },
  uploader:   { label: '上传', color: 'var(--ms-amber)',   bg: '#FEF3E8' },
  downloader: { label: '下载', color: 'var(--ms-emerald)', bg: 'var(--ms-emerald-soft)' },
  viewer:     { label: '查看', color: 'var(--ms-ink-muted)', bg: 'var(--ms-hairline-soft)' },
};
const ROLE_ORDER: ProjectRole[] = ['admin', 'uploader', 'downloader', 'viewer'];

interface Props {
  open: boolean;
  onClose: () => void;
  project: Project;
  me: Me;
}

export function ProjectMembersDrawer({ open, onClose, project, me }: Props) {
  const [inviteOpen, setInviteOpen] = useState(false);
  const qc = useQueryClient();
  const { message } = App.useApp();

  const { data: members, isLoading } = useQuery({
    queryKey: ['project-members', project.id],
    queryFn: async () =>
      (await http.get<Member[]>(`/api/v1/projects/${project.id}/members`)).data,
    enabled: open,
  });

  const invalidate = () => qc.invalidateQueries({ queryKey: ['project-members', project.id] });

  const remove = async (m: Member, role: ProjectRole) => {
    try {
      await http.delete(`/api/v1/projects/${project.id}/members`, {
        params: { subject: m.subject, role },
      });
      message.success(`已撤 ${m.name} 的 ${ROLE_META[role].label} 权限`);
      invalidate();
    } catch (e) {
      message.error(errorMessage(e, '撤销失败'));
    }
  };

  return (
    <Drawer
      title={
        <div>
          <div style={{
            fontSize: 10, letterSpacing: '0.08em', textTransform: 'uppercase',
            color: 'var(--ms-ink-subtle)', fontFamily: 'var(--ms-font-mono)',
            fontWeight: 500, marginBottom: 4,
          }}>Project · Members</div>
          <div style={{
            fontFamily: 'var(--ms-font-display)', fontSize: 17, fontWeight: 500,
            color: 'var(--ms-ink)',
          }}>{project.name}</div>
        </div>
      }
      open={open}
      onClose={onClose}
      width={480}
      styles={{ body: { padding: 0 } }}
      extra={
        <Button type="primary" icon={<Plus size={14} strokeWidth={2.2} />}
                onClick={() => setInviteOpen(true)}>
          邀请
        </Button>
      }
    >
      <div style={{ padding: '16px 20px' }}>
        {isLoading ? (
          <Skeleton active paragraph={{ rows: 4 }} />
        ) : !members || members.length === 0 ? (
          <div style={{
            padding: '40px 16px', textAlign: 'center',
            fontSize: 13, color: 'var(--ms-ink-subtle)',
            border: '1px dashed var(--ms-hairline)',
            borderRadius: 'var(--ms-radius-md)',
          }}>
            还没有成员<br/>点击右上"邀请"开始
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {members.map(m => (
              <MemberCard
                key={m.subject} member={m}
                onRevoke={(role) => remove(m, role)}
              />
            ))}
          </div>
        )}
      </div>

      <InviteModal
        open={inviteOpen}
        onClose={() => setInviteOpen(false)}
        project={project}
        me={me}
        onSuccess={invalidate}
      />
    </Drawer>
  );
}

// ─── MemberCard ──────────────────────────────────────────────────────────────
function MemberCard({
  member, onRevoke,
}: { member: Member; onRevoke: (role: ProjectRole) => void }) {
  const KindIcon = member.kind === 'group' ? UsersIcon
    : member.kind === 'department' ? Building2 : null;
  const initial = (member.name || '?').slice(0, 1).toUpperCase();
  const sorted = [...member.roles].sort(
    (a, b) => ROLE_ORDER.indexOf(a) - ROLE_ORDER.indexOf(b)
  );

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 12,
      padding: '10px 12px',
      background: 'var(--ms-surface)',
      border: '1px solid var(--ms-hairline)',
      borderRadius: 'var(--ms-radius-md)',
    }}>
      {member.kind === 'user' ? (
        <span style={{
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          width: 32, height: 32, flexShrink: 0,
          background: 'var(--ms-ink)', color: 'var(--ms-canvas)',
          borderRadius: '50%',
          fontFamily: 'var(--ms-font-display)', fontSize: 13, fontWeight: 500,
        }}>{initial}</span>
      ) : (
        <span style={{
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          width: 32, height: 32, flexShrink: 0,
          background: 'var(--ms-hairline-soft)', color: 'var(--ms-ink-muted)',
          borderRadius: 'var(--ms-radius-sm)',
        }}>{KindIcon && <KindIcon size={15} strokeWidth={1.7} />}</span>
      )}

      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          fontSize: 13, color: 'var(--ms-ink)', fontWeight: 500,
          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        }}>
          {member.name}
          {sorted.includes('admin') && (
            <Tooltip title="项目管理员">
              <ShieldCheck size={11} strokeWidth={2}
                           style={{ marginLeft: 6, verticalAlign: -1,
                                    color: 'var(--ms-accent)' }} />
            </Tooltip>
          )}
        </div>
        <div style={{
          marginTop: 4, display: 'flex', flexWrap: 'wrap', gap: 4,
        }}>
          {sorted.map(role => (
            <RoleBadge key={role} role={role} onRevoke={() => onRevoke(role)} />
          ))}
        </div>
      </div>
    </div>
  );
}

function RoleBadge({ role, onRevoke }: { role: ProjectRole; onRevoke: () => void }) {
  const meta = ROLE_META[role];
  return (
    <Popconfirm title={`撤销「${meta.label}」?`}
                okText="撤销" okButtonProps={{ danger: true }}
                onConfirm={onRevoke}>
      <span style={{
        display: 'inline-flex', alignItems: 'center', gap: 4,
        padding: '1px 6px 1px 8px',
        background: meta.bg, color: meta.color,
        fontSize: 10.5, fontWeight: 500, letterSpacing: '0.02em',
        borderRadius: 3, cursor: 'pointer',
      }}>
        {meta.label}
        <Trash2 size={9} strokeWidth={2}
                style={{ opacity: 0.6 }} />
      </span>
    </Popconfirm>
  );
}

// ─── InviteModal ─────────────────────────────────────────────────────────────
function InviteModal({
  open, onClose, project, me, onSuccess,
}: {
  open: boolean; onClose: () => void;
  project: Project; me: Me; onSuccess: () => void;
}) {
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [role, setRole] = useState<ProjectRole>('viewer');
  const [loading, setLoading] = useState(false);
  const { message } = App.useApp();

  // admin 角色 model 不接 department#member,SubjectPicker 隐藏 dept tab
  const allowedKinds = role === 'admin'
    ? (['user', 'group'] as const)
    : (['user', 'group', 'department'] as const);

  const submit = async () => {
    if (subjects.length === 0) {
      message.warning('请选至少一个主体');
      return;
    }
    setLoading(true);
    let ok = 0, fail = 0;
    for (const s of subjects) {
      try {
        const body: Record<string, string> = { role };
        if (s.kind === 'user') body.user_open_id = s.id;
        else if (s.kind === 'group') body.group_id = s.id;
        else body.department_id = s.id;
        await http.post(`/api/v1/projects/${project.id}/members`, body);
        ok++;
      } catch (e) {
        fail++;
        message.error(`${s.name || s.id}: ${errorMessage(e)}`);
      }
    }
    setLoading(false);
    if (ok > 0) {
      message.success(`已添加 ${ok} 个主体为「${ROLE_META[role].label}」${fail > 0 ? ` · 失败 ${fail}` : ''}`);
      onSuccess();
      setSubjects([]);
      onClose();
    }
  };

  return (
    <Modal
      title={`添加成员 → ${project.name}`}
      open={open}
      onCancel={onClose}
      onOk={submit}
      okText="添加"
      confirmLoading={loading}
      destroyOnClose
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16, paddingTop: 4 }}>
        <div>
          <FieldLabel>添加主体(用户 / 用户组 / 部门)</FieldLabel>
          <SubjectPicker
            value={subjects}
            onChange={setSubjects}
            me={me}
            allowedKinds={[...allowedKinds]}
          />
          {role === 'admin' && (
            <div style={{ marginTop: 6, fontSize: 11, color: 'var(--ms-ink-subtle)' }}>
              admin 角色仅允许用户 / 用户组(部门不能直接作为 admin)
            </div>
          )}
        </div>
        <div>
          <FieldLabel>角色</FieldLabel>
          <Segmented
            block
            value={role}
            onChange={(v) => setRole(v as ProjectRole)}
            options={ROLE_ORDER.map(r => ({
              label: ROLE_META[r].label, value: r,
            }))}
          />
          <div style={{
            marginTop: 8, fontSize: 11, color: 'var(--ms-ink-subtle)', lineHeight: 1.6,
          }}>
            {role === 'admin' && '管理:全部权限 + 可管成员 + 可建 sensitive 目录'}
            {role === 'uploader' && '上传:可上传文件 + 创建子文件夹 + 自动含查看权限'}
            {role === 'downloader' && '下载:可下载文件 + 自动含查看权限'}
            {role === 'viewer' && '查看:仅元数据浏览,不能下载/上传'}
          </div>
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
