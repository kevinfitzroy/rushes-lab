/**
 * /admin/users — 本地用户管理(#150 数据源本地化)。
 * 系统 admin 创建本地账号(临时密码 + must_change_password)、停用/启用、重置密码。
 * backend 对目录接口 enforce system admin;前端仅做体验提示。
 */
import {
  Alert, App, Button, Empty, Form, Input, Modal, Select, Skeleton, Tooltip,
} from 'antd';
import { KeyRound, Power, RotateCcw, UserPlus } from 'lucide-react';
import { useState } from 'react';
import dayjs from 'dayjs';
import { useMe, useCreateUser, useDisableUser, useEnableUser,
         useDirectoryUsers, useResetUserPassword } from '../api/hooks';
import { errorMessage } from '../api/client';
import type { DirectoryUser, DirectoryUserCreateOut } from '../api/types';

export default function AdminUsersPage() {
  const { data: me } = useMe();
  const [q, setQ] = useState('');
  const [isActive, setIsActive] = useState<boolean | undefined>(undefined);
  const { data, isLoading } = useDirectoryUsers({ q, is_active: isActive });

  if (me && !me.is_system_admin) {
    return (
      <div className="ms-enter" style={{ maxWidth: 520 }}>
        <Alert
          type="warning" showIcon
          message="只有系统管理员可以管理用户"
          description="如需创建本地账号,请联系系统管理员。"
        />
      </div>
    );
  }

  return (
    <div className="ms-enter">
      <UsersHeader />
      <FilterBar q={q} setQ={setQ} isActive={isActive} setIsActive={setIsActive} />
      {isLoading ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {[0, 1, 2].map(i => (
            <div key={i} style={{
              padding: '16px 20px', background: 'var(--ms-surface)',
              border: '1px solid var(--ms-hairline)', borderRadius: 'var(--ms-radius-md)',
            }}>
              <Skeleton active title={{ width: '40%' }} paragraph={{ rows: 1 }} />
            </div>
          ))}
        </div>
      ) : !data || data.length === 0 ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE}
               description={<span style={{ color: 'var(--ms-ink-subtle)' }}>无用户</span>}
               style={{ marginTop: 60 }} />
      ) : (
        <div className="ms-enter-stagger"
             style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {data.map(u => <UserRow key={u.id} user={u} />)}
        </div>
      )}
    </div>
  );
}

function UsersHeader() {
  const [open, setOpen] = useState(false);
  return (
    <div style={{
      display: 'flex', alignItems: 'baseline', justifyContent: 'space-between',
      gap: 24, marginBottom: 'var(--ms-sp-xl)',
    }}>
      <div>
        <h1 style={{
          margin: 0, fontFamily: 'var(--ms-font-display)',
          fontSize: 32, fontWeight: 500, letterSpacing: '-0.02em',
          color: 'var(--ms-ink)', lineHeight: 1.1,
        }}>用户</h1>
        <p style={{ margin: '8px 0 0', fontSize: 13, color: 'var(--ms-ink-muted)' }}>
          本地账号(ADR-0007)创建 / 停用 / 重置密码 — 停用立即撤销全部权限并禁止登录
        </p>
      </div>
      <Button type="primary" icon={<UserPlus size={14} strokeWidth={2} />}
              onClick={() => setOpen(true)}>
        新建用户
      </Button>
      <CreateUserModal open={open} onClose={() => setOpen(false)} />
    </div>
  );
}

function FilterBar({ q, setQ, isActive, setIsActive }: {
  q: string; setQ: (v: string) => void;
  isActive: boolean | undefined; setIsActive: (v: boolean | undefined) => void;
}) {
  return (
    <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center' }}>
      <Input.Search
        value={q}
        onChange={e => setQ(e.target.value)}
        onSearch={v => setQ(v.trim())}
        allowClear placeholder="搜用户名 / 姓名 / 邮箱…"
        style={{ width: 260 }} />
      <Select
        value={isActive === undefined ? '' : isActive}
        onChange={(v) => setIsActive(v === '' ? undefined : v as boolean)}
        style={{ width: 120 }}
        options={[
          { value: '', label: '全部状态' },
          { value: true, label: '启用' },
          { value: false, label: '停用' },
        ]} />
    </div>
  );
}

function UserRow({ user }: { user: DirectoryUser }) {
  const { message } = App.useApp();
  const disable = useDisableUser();
  const enable = useEnableUser();
  const reset = useResetUserPassword();
  const [pw, setPw] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const doDisable = async () => {
    setBusy(true);
    try {
      await disable.mutateAsync(user.id);
      message.success(`已停用 ${user.name} — 其全部权限 tuple 已撤销`);
    } catch (e) {
      message.error(errorMessage(e, '停用失败'));
    } finally { setBusy(false); }
  };
  const doEnable = async () => {
    setBusy(true);
    try {
      await enable.mutateAsync(user.id);
      message.success(`已重新启用 ${user.name}`);
    } catch (e) {
      message.error(errorMessage(e, '启用失败'));
    } finally { setBusy(false); }
  };
  const doReset = async () => {
    setBusy(true);
    try {
      const out = await reset.mutateAsync(user.id);
      setPw(out.temporary_password);
    } catch (e) {
      message.error(errorMessage(e, '重置失败'));
    } finally { setBusy(false); }
  };

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 12,
      padding: '12px 16px', background: 'var(--ms-surface)',
      border: '1px solid var(--ms-hairline)', borderRadius: 'var(--ms-radius-md)',
    }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--ms-ink)' }}>{user.name}</span>
          <StatusPill active={user.is_active} mustChange={user.must_change_password} />
          {!user.is_active && user.resigned_at && (
            <Tooltip title={`停用于 ${dayjs(user.resigned_at).format('YYYY-MM-DD HH:mm')}`}>
              <span style={{ fontSize: 11, color: 'var(--ms-ink-subtle)' }}>已停用</span>
            </Tooltip>
          )}
        </div>
        <div style={{
          marginTop: 3, fontSize: 11.5, color: 'var(--ms-ink-muted)',
          fontFamily: 'var(--ms-font-mono)',
          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        }}>
          {user.username || '—'}{user.email ? ` · ${user.email}` : ''}
        </div>
      </div>
      <span style={{ fontSize: 11.5, color: 'var(--ms-ink-subtle)', whiteSpace: 'nowrap' }}>
        创建于 {dayjs(user.created_at).format('YYYY-MM-DD')}
      </span>
      <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
        {user.is_active ? (
          <Button size="small" danger icon={<Power size={12} strokeWidth={2} />}
                  loading={busy} onClick={doDisable}>
            停用
          </Button>
        ) : (
          <Button size="small" icon={<Power size={12} strokeWidth={2} />}
                  loading={busy} onClick={doEnable}>
            启用
          </Button>
        )}
        <Button size="small" icon={<RotateCcw size={12} strokeWidth={2} />}
                loading={busy} onClick={doReset}>
          重置密码
        </Button>
      </div>
      <TempPasswordModal open={!!pw} password={pw} onClose={() => setPw(null)} />
    </div>
  );
}

function StatusPill({ active, mustChange }: { active: boolean; mustChange: boolean }) {
  return (
    <>
      <span style={{
        fontFamily: 'var(--ms-font-mono)', fontSize: 10.5,
        fontWeight: 500, padding: '1px 7px', borderRadius: 3,
        color: active ? 'var(--ms-emerald)' : 'var(--ms-crimson)',
        background: active ? 'var(--ms-emerald)14' : 'var(--ms-crimson)14',
      }}>
        {active ? '启用' : '停用'}
      </span>
      {mustChange && (
        <span style={{
          fontFamily: 'var(--ms-font-mono)', fontSize: 10.5,
          fontWeight: 500, padding: '1px 7px', borderRadius: 3,
          color: 'var(--ms-amber)', background: 'var(--ms-amber)14',
        }}>
          待改密
        </span>
      )}
    </>
  );
}

// ─── 新建用户 ───────────────────────────────────────────────────────────────
function CreateUserModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const create = useCreateUser();
  const [form] = Form.useForm();
  const { message } = App.useApp();
  const [created, setCreated] = useState<DirectoryUserCreateOut | null>(null);

  const submit = async () => {
    try {
      const v = await form.validateFields();
      const out = await create.mutateAsync({
        username: v.username.trim(),
        name: v.name.trim(),
        email: v.email?.trim() || undefined,
      });
      setCreated(out);
      message.success(`用户 "${out.name}" 已创建`);
      onClose();
      form.resetFields();
    } catch (e) {
      if ((e as { errorFields?: unknown }).errorFields) return;
      message.error(errorMessage(e, '创建失败'));
    }
  };

  return (
    <>
      <Modal title="新建本地用户" open={open} onCancel={onClose} destroyOnClose
             confirmLoading={create.isPending} onOk={submit} okText="创建">
        <Form form={form} layout="vertical">
          <Form.Item name="username" label="登录名(拼音 / 工号,登录用)"
                     rules={[
                       { required: true, min: 2, max: 64 },
                       { pattern: /^[a-zA-Z0-9._-]+$/, message: '仅字母/数字/._- 组成' },
                     ]}
                     extra="提交后不可改;本地用户无飞书身份,登录名是唯一标识">
            <Input placeholder="zhangsan / 10086" autoFocus />
          </Form.Item>
          <Form.Item name="name" label="姓名" rules={[{ required: true, max: 128 }]}>
            <Input placeholder="张三" />
          </Form.Item>
          <Form.Item name="email" label="邮箱(可选)">
            <Input placeholder="zhangsan@example.com" />
          </Form.Item>
          <Alert type="info" showIcon style={{ marginBottom: 8 }}
                 message="创建成功后会显示一次性临时密码,用户首次登录需改密。" />
        </Form>
      </Modal>
      <TempPasswordModal open={!!created} password={created?.temporary_password ?? null}
                         onClose={() => setCreated(null)}
                         title="用户已创建" />
    </>
  );
}

// ─── 临时密码展示(创建 / 重置共用,只回显一次)────────────────────────────
function TempPasswordModal({ open, password, onClose, title }: {
  open: boolean; password: string | null; onClose: () => void; title?: string;
}) {
  const { message } = App.useApp();
  const copy = async () => {
    if (!password) return;
    try {
      await navigator.clipboard.writeText(password);
      message.success('已复制');
    } catch {
      message.error('复制失败,请手动选中');
    }
  };
  return (
    <Modal title={title || '临时密码'} open={open} onCancel={onClose}
           footer={<Button type="primary" onClick={onClose}>完成</Button>}>
      <p style={{ fontSize: 13, color: 'var(--ms-ink-muted)', lineHeight: 1.7, marginTop: 0 }}>
        这是<strong>唯一一次</strong>展示,不会写入日志 / 审计。请直接交给对方,首次登录后必须修改。
      </p>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8,
        padding: '12px 14px', background: 'var(--ms-canvas)',
        border: '1px solid var(--ms-hairline)', borderRadius: 'var(--ms-radius-sm)',
      }}>
        <KeyRound size={15} strokeWidth={1.8} style={{ color: 'var(--ms-ink-muted)', flexShrink: 0 }} />
        <code style={{
          flex: 1, fontFamily: 'var(--ms-font-mono)', fontSize: 15,
          color: 'var(--ms-ink)', letterSpacing: '0.04em',
          overflowWrap: 'anywhere',
        }}>{password}</code>
        <Button size="small" onClick={copy}>复制</Button>
      </div>
    </Modal>
  );
}
