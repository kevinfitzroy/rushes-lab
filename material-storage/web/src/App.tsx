import { App as AntApp, ConfigProvider, Layout, Menu, Spin, Typography, theme } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { HashRouter, Link, Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { useMe } from './api/hooks';
import { apiBase } from './api/client';

import ProjectsPage from './pages/ProjectsPage';
import ProjectDetailPage from './pages/ProjectDetailPage';
import FolderDetailPage from './pages/FolderDetailPage';
import ApprovalsPage from './pages/ApprovalsPage';
import DevLoginPage from './pages/DevLoginPage';

const qc = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, refetchOnWindowFocus: false } },
});

function AppShell() {
  const { data: me, isLoading, isError } = useMe();
  const location = useLocation();

  // dev login page bypass auth
  if (location.pathname === '/dev-login') {
    return (
      <Routes>
        <Route path="/dev-login" element={<DevLoginPage />} />
      </Routes>
    );
  }

  if (isLoading) return <div style={{ padding: 100, textAlign: 'center' }}><Spin /></div>;
  if (isError || !me) {
    // dev 模式给一个选项跳 /dev-login;否则跳真 OIDC
    if (import.meta.env.DEV || window.location.search.includes('dev=1') || window.location.hash.includes('dev=1')) {
      window.location.hash = '#/dev-login';
      window.location.reload();
      return null;
    }
    window.location.href = `${apiBase}/api/v1/auth/login?next=${encodeURIComponent(location.pathname)}`;
    return null;
  }

  const selectedKey = location.pathname.startsWith('/approvals') ? 'approvals' : 'projects';

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Layout.Header style={{ display: 'flex', alignItems: 'center', gap: 24 }}>
        <Typography.Text strong style={{ color: '#fff', fontSize: 16 }}>material-storage</Typography.Text>
        <Menu theme="dark" mode="horizontal" selectedKeys={[selectedKey]} style={{ flex: 1 }}
              items={[
                { key: 'projects', label: <Link to="/">项目</Link> },
                { key: 'approvals', label: <Link to="/approvals">审批</Link> },
              ]}/>
        <Typography.Text style={{ color: '#bbb' }}>{me.name}</Typography.Text>
      </Layout.Header>
      <Layout.Content style={{ padding: 24, maxWidth: 1280, margin: '0 auto', width: '100%' }}>
        <Routes>
          <Route path="/" element={<ProjectsPage />} />
          <Route path="/projects/:projectId" element={<ProjectDetailPage />} />
          <Route path="/folders/:folderId" element={<FolderDetailPage />} />
          <Route path="/approvals" element={<ApprovalsPage />} />
          <Route path="/dev-login" element={<DevLoginPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Layout.Content>
      <Layout.Footer style={{ textAlign: 'center', color: '#999' }}>
        material-storage Phase B-3 · {new Date().getFullYear()}
      </Layout.Footer>
    </Layout>
  );
}

export default function App() {
  return (
    <ConfigProvider locale={zhCN} theme={{ algorithm: theme.defaultAlgorithm }}>
      <AntApp>
        <QueryClientProvider client={qc}>
          <HashRouter>
            <AppShell />
          </HashRouter>
        </QueryClientProvider>
      </AntApp>
    </ConfigProvider>
  );
}
