import { Avatar, Dropdown } from 'antd';
import { LogOut, User as UserIcon } from 'lucide-react';
import { Link } from 'react-router-dom';
import { apiBase, setDevUserId, getDevUserId, http } from '../api/client';
import type { Me } from '../api/types';

export function UserMenu({ me }: { me: Me }) {
  const isDev = !!getDevUserId();

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
              <div style={{ padding: '4px 0', minWidth: 200 }}>
                <div style={{ fontWeight: 500, color: 'var(--ms-ink)' }}>{me.name}</div>
                <div style={{ fontSize: 11, color: 'var(--ms-ink-subtle)',
                              fontFamily: 'var(--ms-font-mono)', marginTop: 2 }}>
                  {me.open_id?.slice(0, 16)}…
                </div>
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
