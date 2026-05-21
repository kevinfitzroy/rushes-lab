/**
 * ProjectMembersDrawer — 项目成员管理(D iter4)。
 * 入口:ProjectDetailPage 顶栏"成员"按钮。
 *
 * 成员卡片:头像/icon + name + roles 徽章串 + per-role 撤销 + 邀请按钮。
 * 邀请 Modal:UserPicker + role segmented control(admin/uploader/downloader/viewer)。
 */
import { App, Button, Drawer, Modal, Popconfirm, Segmented, Skeleton, Tooltip } from 'antd';
import {
  Building2, Clock, FolderLock, Folder as FolderIcon, Infinity as InfinityIcon,
  Layers, Plus, ShieldCheck, Trash2, Users as UsersIcon,
} from 'lucide-react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import dayjs from 'dayjs';
import 'dayjs/locale/zh-cn';
import relativeTime from 'dayjs/plugin/relativeTime';
import { http, errorMessage } from '../api/client';
import type { Me, Project } from '../api/types';
import { SubjectPicker, type Subject } from './SubjectPicker';

dayjs.extend(relativeTime);
dayjs.locale('zh-cn');

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

// ─── 授权总览 (#138) ──────────────────────────────────────────────────────────
interface Grant {
  subject: string;
  kind: 'user' | 'group' | 'department';
  subject_id: string;
  name: string;
  object_type: 'project' | 'folder' | 'sensitive_folder';
  object_id: string;
  object_name: string | null;
  relation: string;
  level: 'view' | 'download' | 'upload';
  permanent: boolean;
  expires_at: string | null;
}

const LEVEL_META: Record<Grant['level'], { label: string; color: string; bg: string }> = {
  view:     { label: '查看', color: 'var(--ms-ink-muted)', bg: 'var(--ms-hairline-soft)' },
  download: { label: '下载', color: 'var(--ms-emerald)',   bg: 'var(--ms-emerald-soft)' },
  upload:   { label: '上传', color: 'var(--ms-amber)',     bg: '#FEF3E8' },
};

const OBJECT_META: Record<Grant['object_type'],
  { label: string; Icon: React.ComponentType<{ size?: number; strokeWidth?: number }> }> = {
  project:          { label: '整个项目', Icon: Layers },
  folder:           { label: '文件夹',   Icon: FolderIcon },
  sensitive_folder: { label: '敏感目录', Icon: FolderLock },
};

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

  // #138 授权总览:project + folder/sensitive_folder 的 explicit/invited grant
  const { data: grants, isLoading: grantsLoading } = useQuery({
    queryKey: ['project-grants', project.id],
    queryFn: async () =>
      (await http.get<Grant[]>(`/api/v1/projects/${project.id}/grants`)).data,
    enabled: open,
  });

  const revokeGrant = async (g: Grant) => {
    try {
      await http.delete(`/api/v1/projects/${project.id}/grants`, {
        params: {
          object_type: g.object_type, object_id: g.object_id,
          subject: g.subject, relation: g.relation,
        },
      });
      message.success(`已撤回 ${g.name} 对「${g.object_name ?? OBJECT_META[g.object_type].label}」的授权`);
      qc.invalidateQueries({ queryKey: ['project-grants', project.id] });
    } catch (e) {
      message.error(errorMessage(e, '撤回失败'));
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
      <div style={{
        padding: '16px 20px',
        display: 'flex', flexDirection: 'column', gap: 24,
      }}>
        {/* 直接成员 — 项目级角色 */}
        <section>
          <SectionLabel title="直接成员"
                        hint="项目级角色:管理 / 上传 / 下载 / 查看" />
          {isLoading ? (
            <Skeleton active paragraph={{ rows: 4 }} />
          ) : !members || members.length === 0 ? (
            <EmptyHint>还没有成员 · 点右上「邀请」开始</EmptyHint>
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
        </section>

        {/* 授权总览 (#138) — 通过审批/邀请获得的 explicit/invited grant */}
        <section>
          <SectionLabel title="授权总览"
                        hint="通过审批 / 邀请获得的授权(含临时与永久),可在此撤回" />
          {grantsLoading ? (
            <Skeleton active paragraph={{ rows: 3 }} />
          ) : !grants || grants.length === 0 ? (
            <EmptyHint>暂无额外授权 · 审批通过 / 文件夹邀请的授权会出现在这里</EmptyHint>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {grants.map(g => (
                <GrantCard
                  key={`${g.object_type}:${g.object_id}:${g.subject}:${g.relation}`}
                  grant={g} onRevoke={() => revokeGrant(g)}
                />
              ))}
            </div>
          )}
        </section>
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

// ─── SectionLabel / EmptyHint ────────────────────────────────────────────────
function SectionLabel({ title, hint }: { title: string; hint: string }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{
        fontFamily: 'var(--ms-font-display)', fontSize: 13, fontWeight: 500,
        color: 'var(--ms-ink)', letterSpacing: '-0.01em',
      }}>{title}</div>
      <div style={{ fontSize: 11, color: 'var(--ms-ink-subtle)', marginTop: 2 }}>{hint}</div>
    </div>
  );
}

function EmptyHint({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      padding: '28px 16px', textAlign: 'center',
      fontSize: 12.5, color: 'var(--ms-ink-subtle)',
      border: '1px dashed var(--ms-hairline)',
      borderRadius: 'var(--ms-radius-md)',
    }}>{children}</div>
  );
}

// ─── GrantCard (#138) ─────────────────────────────────────────────────────────
function GrantCard({ grant, onRevoke }: { grant: Grant; onRevoke: () => void }) {
  const KindIcon = grant.kind === 'group' ? UsersIcon
    : grant.kind === 'department' ? Building2 : null;
  const initial = (grant.name || '?').slice(0, 1).toUpperCase();
  const lvl = LEVEL_META[grant.level];
  const obj = OBJECT_META[grant.object_type];
  const ObjIcon = obj.Icon;
  const scopeName = grant.object_name ?? obj.label;

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 12,
      padding: '10px 12px',
      background: 'var(--ms-surface)',
      border: '1px solid var(--ms-hairline)',
      borderRadius: 'var(--ms-radius-md)',
    }}>
      {grant.kind === 'user' ? (
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
          display: 'flex', alignItems: 'center', gap: 6,
        }}>
          <span style={{
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            flex: '0 1 auto', minWidth: 0,
          }}>{grant.name}</span>
          <KindTag kind={grant.kind} />
        </div>
        <div style={{
          marginTop: 5, display: 'flex', alignItems: 'center', gap: 8,
          flexWrap: 'wrap', fontSize: 11.5,
        }}>
          {/* 动作徽章 */}
          <span style={{
            padding: '2px 7px', background: lvl.bg, color: lvl.color,
            borderRadius: 3, fontSize: 11, fontWeight: 500, letterSpacing: '0.02em',
          }}>{lvl.label}</span>
          {/* 资源范围 */}
          <Tooltip title={`授权范围:${obj.label}`}>
            <span style={{
              display: 'inline-flex', alignItems: 'center', gap: 4,
              color: 'var(--ms-ink-muted)', maxWidth: 160,
            }}>
              <ObjIcon size={11} strokeWidth={1.8} />
              <span style={{
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
              }}>{scopeName}</span>
            </span>
          </Tooltip>
          {/* 有效期 */}
          {grant.permanent ? (
            <span style={{
              display: 'inline-flex', alignItems: 'center', gap: 3,
              color: 'var(--ms-ink-subtle)',
            }}>
              <InfinityIcon size={11} strokeWidth={1.8} /> 长期
            </span>
          ) : grant.expires_at ? (
            <Tooltip title={dayjs(grant.expires_at).format('YYYY-MM-DD HH:mm')}>
              <span style={{
                display: 'inline-flex', alignItems: 'center', gap: 3,
                color: 'var(--ms-amber)',
              }}>
                <Clock size={11} strokeWidth={2} /> {dayjs(grant.expires_at).fromNow()}到期
              </span>
            </Tooltip>
          ) : null}
        </div>
      </div>

      {/* 撤回 */}
      <Popconfirm
        title="撤回此授权?"
        description={`将撤回 ${grant.name} 对「${scopeName}」的${lvl.label}授权${
          grant.permanent ? ',对方将立即失去访问' : ''
        }`}
        okText="撤回" okButtonProps={{ danger: true }}
        onConfirm={onRevoke}
      >
        <Tooltip title="撤回授权" mouseEnterDelay={0.3}>
          <Button size="small" type="text" danger
                  icon={<Trash2 size={14} strokeWidth={2} />}
                  style={{ flexShrink: 0 }} />
        </Tooltip>
      </Popconfirm>
    </div>
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
          display: 'flex', alignItems: 'center', gap: 6,
        }}>
          <span style={{
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            flex: '0 1 auto', minWidth: 0,
          }}>{member.name}</span>
          <KindTag kind={member.kind} />
          {sorted.includes('admin') && (
            <Tooltip title="项目管理员">
              <ShieldCheck size={11} strokeWidth={2}
                           style={{ color: 'var(--ms-accent)', flexShrink: 0 }} />
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

function KindTag({ kind }: { kind: Member['kind'] }) {
  const meta = kind === 'user'
    ? { label: '用户', tip: '直接授权给个人' }
    : kind === 'group'
      ? { label: '群组', tip: '通过用户组继承' }
      : { label: '部门', tip: '通过飞书部门继承' };
  return (
    <Tooltip title={meta.tip}>
      <span style={{
        flexShrink: 0,
        padding: '0 5px',
        fontSize: 9.5, letterSpacing: '0.04em',
        fontFamily: 'var(--ms-font-mono)',
        color: 'var(--ms-ink-subtle)',
        background: 'var(--ms-hairline-soft)',
        borderRadius: 2,
        lineHeight: '14px',
      }}>{meta.label}</span>
    </Tooltip>
  );
}

function RoleBadge({ role, onRevoke }: { role: ProjectRole; onRevoke: () => void }) {
  const meta = ROLE_META[role];
  return (
    <Popconfirm title={`撤销「${meta.label}」?`}
                okText="撤销" okButtonProps={{ danger: true }}
                onConfirm={onRevoke}>
      <Tooltip title="点击撤销该角色" mouseEnterDelay={0.3}>
        <span className="ms-role-badge" style={{
          display: 'inline-flex', alignItems: 'center', gap: 5,
          padding: '3px 9px 3px 10px',
          background: meta.bg, color: meta.color,
          fontSize: 12, fontWeight: 500, letterSpacing: '0.02em',
          borderRadius: 4, cursor: 'pointer',
          transition: 'filter 0.14s, transform 0.14s',
        }}>
          {meta.label}
          <Trash2 size={13} strokeWidth={2}
                  style={{ opacity: 0.85, marginLeft: 1 }} />
        </span>
      </Tooltip>
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
