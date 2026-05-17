import { App, Avatar, Dropdown } from 'antd';
import { Check, Copy, LogOut, User as UserIcon } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { apiBase, setDevUserId, getDevUserId, http } from '../api/client';
import type { Me } from '../api/types';

export function UserMenu({ me }: { me: Me }) {
  const isDev = !!getDevUserId();
  const { message } = App.useApp();
  const [copied, setCopied] = useState(false);

  const copyOpenId = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!me.open_id) return;
    try {
      await navigator.clipboard.writeText(me.open_id);
      setCopied(true);
      message.success('open_id 已复制');
      setTimeout(() => setCopied(false), 1500);
    } catch {
      message.error('复制失败');
    }
  };

  const handleLogout = async () => {
    if (isDev) {
      setDevUserId(null);
      window.location.reload();
      return;
    }
    try { await http.post('/api/v1/auth/logout'); } catch { /* ignore */ }
    window.location.href = `${apiBase}/api/v1/auth/login`;
  };

  // 头像 fallback:用名字首字
  const initial = (me.name || '?').slice(0, 1).toUpperCase();

  return (
    <Dropdown
      menu={{
        items: [
          {
            key: 'me',
            label: (
              <div style={{ padding: '4px 0', minWidth: 260, maxWidth: 360 }}>
                <div style={{ fontWeight: 500, color: 'var(--ms-ink)' }}>{me.name}</div>
                {me.open_id && (
                  <div style={{
                    marginTop: 4,
                    display: 'flex', alignItems: 'center', gap: 6,
                    fontSize: 11, color: 'var(--ms-ink-subtle)',
                    fontFamily: 'var(--ms-font-mono)',
                  }}>
                    <span style={{
                      flex: 1, minWidth: 0,
                      overflow: 'hidden', textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }} title={me.open_id}>
                      {me.open_id}
                    </span>
                    <button
                      type="button"
                      onClick={copyOpenId}
                      title={copied ? '已复制' : '复制 open_id'}
                      style={{
                        display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                        width: 22, height: 22, flexShrink: 0,
                        padding: 0, border: 'none', cursor: 'pointer',
                        background: 'transparent',
                        color: copied ? 'var(--ms-emerald)' : 'var(--ms-ink-subtle)',
                        borderRadius: 4,
                        transition: 'background var(--ms-dur-fast) var(--ms-ease)',
                      }}
                      onMouseEnter={e => {
                        e.currentTarget.style.background = 'var(--ms-hairline-soft)';
                      }}
                      onMouseLeave={e => {
                        e.currentTarget.style.background = 'transparent';
                      }}
                    >
                      {copied
                        ? <Check size={13} strokeWidth={2.2} />
                        : <Copy size={12} strokeWidth={1.8} />}
                    </button>
                  </div>
                )}
              </div>
            ),
            disabled: true,
          },
          { type: 'divider' },
          { key: 'apps', icon: <UserIcon size={14} />, label: <Link to="/approvals">我的申请</Link> },
          { type: 'divider' },
          { key: 'logout', icon: <LogOut size={14} />, label: '退出登录',
            onClick: handleLogout, danger: true },
        ],
      }}
      placement="bottomRight"
      trigger={['click']}
    >
      <button
        type="button"
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 10,
          padding: '4px 12px 4px 4px',
          border: '1px solid transparent',
          background: 'transparent',
          borderRadius: 'var(--ms-radius-md)',
          cursor: 'pointer',
          color: 'var(--ms-ink)',
          fontFamily: 'inherit',
          fontSize: 13,
          transition: `background var(--ms-dur-fast) var(--ms-ease),
                       border-color var(--ms-dur-fast) var(--ms-ease)`,
        }}
        onMouseEnter={e => {
          e.currentTarget.style.background = 'var(--ms-hairline-soft)';
          e.currentTarget.style.borderColor = 'var(--ms-hairline)';
        }}
        onMouseLeave={e => {
          e.currentTarget.style.background = 'transparent';
          e.currentTarget.style.borderColor = 'transparent';
        }}
      >
        <Avatar
          size={28}
          style={{
            background: isDev ? 'var(--ms-amber)' : 'var(--ms-ink)',
            color: 'var(--ms-canvas)',
            fontSize: 12,
            fontWeight: 500,
            fontFamily: 'var(--ms-font-display)',
          }}
        >
          {initial}
        </Avatar>
        <span style={{ maxWidth: 90, overflow: 'hidden', textOverflow: 'ellipsis',
                       whiteSpace: 'nowrap' }}>{me.name}</span>
        {isDev && (
          <span style={{
            fontSize: 10, color: 'var(--ms-amber)', fontFamily: 'var(--ms-font-mono)',
            padding: '2px 5px', borderRadius: 3,
            background: 'rgba(180,83,9,0.1)',
          }}>DEV</span>
        )}
      </button>
    </Dropdown>
  );
}
