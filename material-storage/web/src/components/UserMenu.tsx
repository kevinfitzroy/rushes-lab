import { Avatar, Dropdown, Space, Typography } from 'antd';
import { LogoutOutlined, ProfileOutlined, UserOutlined } from '@ant-design/icons';
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

  return (
    <Dropdown
      menu={{
        items: [
          { key: 'me', icon: <ProfileOutlined />, label: <Link to="/approvals">我的申请</Link> },
          { type: 'divider' },
          { key: 'logout', icon: <LogoutOutlined />, label: '退出登录', onClick: handleLogout, danger: true },
        ],
      }}
      placement="bottomRight"
    >
      <Space style={{ cursor: 'pointer', color: '#fff' }}>
        <Avatar size="small" icon={<UserOutlined />} style={{ background: isDev ? '#f59e0b' : '#3b82f6' }} />
        <Typography.Text style={{ color: '#fff' }}>{me.name}</Typography.Text>
        {isDev && <Typography.Text style={{ color: '#f59e0b', fontSize: 11 }}>[dev]</Typography.Text>}
      </Space>
    </Dropdown>
  );
}
