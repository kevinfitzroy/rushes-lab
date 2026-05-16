import { App as AntApp, ConfigProvider, Layout, Menu, Spin, Typography, theme, message as antMessage } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { HashRouter, Link, Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { useMe } from './api/hooks';
import { apiBase, errorMessage } from './api/client';
import { UserMenu } from './components/UserMenu';

import ProjectsPage from './pages/ProjectsPage';
import ProjectDetailPage from './pages/ProjectDetailPage';
import FolderDetailPage from './pages/FolderDetailPage';
import ApprovalsPage from './pages/ApprovalsPage';
import DevLoginPage from './pages/DevLoginPage';

// 全局 query/mutation 错误统一 toast(401 axios interceptor 已处理跳 OIDC,这里跳过 401)
const qc = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, refetchOnWindowFocus: false, retry: false } },
  queryCache: new QueryCache({
    onError: (err) => {
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 401 || status === 403) return; // 401 跳登录;403 各 page 自己处理
      antMessage.error(errorMessage(err, '数据加载失败'));
    },
  }),
  mutationCache: new MutationCache({
    onError: (err) => {
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 401) return;
      // 403 也 toast(操作类失败 user 应当感知)
      antMessage.error(errorMessage(err, '操作失败'));
    },
  }),
});

function AppShell() {
  const { data: me, isLoading, isError } = useMe();
  const location = useLocation();

  if (location.pathname === '/dev-login') {
    return (
      <Routes>
        <Route path="/dev-login" element={<DevLoginPage />} />
      </Routes>
    );
  }

  if (isLoading) return <div style={{ padding: 100, textAlign: 'center' }}><Spin size="large" tip="加载中…" /></div>;
  if (isError || !me) {
    if (import.meta.env.DEV || window.location.search.includes('dev=1') || window.location.hash.includes('dev=1')) {
      window.location.hash = '#/dev-login';
      window.location.reload();
      return null;
    }
    const next = window.location.pathname + window.location.hash;
    window.location.href = `${apiBase}/api/v1/auth/login?next=${encodeURIComponent(next)}`;
    return null;
  }

  const selectedKey = location.pathname.startsWith('/approvals') ? 'approvals' : 'projects';

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Layout.Header style={{ display: 'flex', alignItems: 'center', gap: 24, padding: '0 24px' }}>
        <Typography.Text strong style={{ color: '#fff', fontSize: 16 }}>material-storage</Typography.Text>
        <Menu theme="dark" mode="horizontal" selectedKeys={[selectedKey]} style={{ flex: 1, minWidth: 0 }}
              items={[
                { key: 'projects', label: <Link to="/">项目</Link> },
                { key: 'approvals', label: <Link to="/approvals">审批</Link> },
              ]}/>
        <UserMenu me={me} />
      </Layout.Header>
      <Layout.Content style={{ padding: '24px', maxWidth: 1400, margin: '0 auto', width: '100%' }}>
        <Routes>
          <Route path="/" element={<ProjectsPage />} />
          <Route path="/projects/:projectId" element={<ProjectDetailPage />} />
          <Route path="/folders/:folderId" element={<FolderDetailPage />} />
          <Route path="/approvals" element={<ApprovalsPage />} />
          <Route path="/dev-login" element={<DevLoginPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Layout.Content>
      <Layout.Footer style={{ textAlign: 'center', color: '#999', fontSize: 12 }}>
        material-storage Phase B-3 · {new Date().getFullYear()}
      </Layout.Footer>
    </Layout>
  );
}

export default function App() {
  return (
    <ConfigProvider locale={zhCN} theme={{
      algorithm: theme.defaultAlgorithm,
      token: { colorPrimary: '#1677ff', borderRadius: 6 },
    }}>
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
