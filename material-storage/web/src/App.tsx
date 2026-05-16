import { App as AntApp, Button, ConfigProvider, Drawer, Grid, Layout, Menu, Spin, Typography, theme, message as antMessage } from 'antd';
import { MenuOutlined } from '@ant-design/icons';
import zhCN from 'antd/locale/zh_CN';
import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Link, Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { Suspense, lazy, useState } from 'react';
import { useMe } from './api/hooks';
import { apiBase, errorMessage } from './api/client';
import { UserMenu } from './components/UserMenu';
import { PersistentUploadDrawer } from './components/PersistentUploadDrawer';
import { UploadFloatingIndicator } from './components/UploadFloatingIndicator';
import { ErrorBoundary } from './components/ErrorBoundary';
import { UploadProvider } from './lib/upload-store';
import { DownloadProvider } from './lib/download-store';

// (2) route-level lazy:首屏只加载当前路由 chunk
const ProjectsPage = lazy(() => import('./pages/ProjectsPage'));
const ProjectDetailPage = lazy(() => import('./pages/ProjectDetailPage'));
const FolderDetailPage = lazy(() => import('./pages/FolderDetailPage'));
const ApprovalsPage = lazy(() => import('./pages/ApprovalsPage'));
const DevLoginPage = lazy(() => import('./pages/DevLoginPage'));

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

const RouterRoutes = () => (
  <Suspense fallback={<div style={{ padding: 80, textAlign: 'center' }}><Spin tip="加载页面…" /></div>}>
    <Routes>
      <Route path="/" element={<ProjectsPage />} />
      <Route path="/projects/:projectId" element={<ProjectDetailPage />} />
      <Route path="/projects/:projectId/folders/:folderId" element={<ProjectDetailPage />} />
      <Route path="/folders/:folderId" element={<FolderDetailPage />} />
      <Route path="/approvals" element={<ApprovalsPage />} />
      <Route path="/dev-login" element={<DevLoginPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  </Suspense>
);

function AppShell() {
  const { data: me, isLoading, isError } = useMe();
  const location = useLocation();
  const screens = Grid.useBreakpoint();
  const isMobile = !screens.md;
  const [menuOpen, setMenuOpen] = useState(false);

  if (location.pathname === '/dev-login') return <RouterRoutes />;

  if (isLoading) return <div style={{ padding: 100, textAlign: 'center' }}><Spin size="large" tip="加载中…" /></div>;
  if (isError || !me) {
    if (import.meta.env.DEV || window.location.search.includes('dev=1')) {
      window.location.href = '/ms-static/web/dev-login';
      return null;
    }
    const next = window.location.pathname + window.location.search;
    window.location.href = `${apiBase}/api/v1/auth/login?next=${encodeURIComponent(next)}`;
    return null;
  }

  const selectedKey = location.pathname.startsWith('/approvals') ? 'approvals' : 'projects';
  const menuItems = [
    { key: 'projects', label: <Link to="/" onClick={() => setMenuOpen(false)}>项目</Link> },
    { key: 'approvals', label: <Link to="/approvals" onClick={() => setMenuOpen(false)}>审批</Link> },
  ];

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Layout.Header style={{ display: 'flex', alignItems: 'center', gap: 16, padding: isMobile ? '0 12px' : '0 24px' }}>
        {isMobile && (
          <Button type="text" icon={<MenuOutlined style={{ color: '#fff' }} />}
                  onClick={() => setMenuOpen(true)} />
        )}
        <Typography.Text strong style={{ color: '#fff', fontSize: 16, whiteSpace: 'nowrap' }}>
          material-storage
        </Typography.Text>
        {!isMobile && (
          <Menu theme="dark" mode="horizontal" selectedKeys={[selectedKey]} items={menuItems}
                style={{ flex: 1, minWidth: 0 }} />
        )}
        <div style={{ flex: 1 }} />
        <UserMenu me={me} />
      </Layout.Header>
      {isMobile && (
        <Drawer title="导航" placement="left" open={menuOpen} onClose={() => setMenuOpen(false)}
                width={260} styles={{ body: { padding: 0 } }}>
          <Menu mode="inline" selectedKeys={[selectedKey]} items={menuItems} style={{ borderInlineEnd: 0 }} />
        </Drawer>
      )}
      <Layout.Content style={{ padding: isMobile ? 12 : 24, maxWidth: 1400, margin: '0 auto', width: '100%' }}>
        <RouterRoutes />
      </Layout.Content>
      <Layout.Footer style={{ textAlign: 'center', color: '#999', fontSize: 12, padding: '16px 12px' }}>
        material-storage Phase B-3 · {new Date().getFullYear()}
      </Layout.Footer>
      <PersistentUploadDrawer />
      <UploadFloatingIndicator />
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
        <ErrorBoundary>
          <QueryClientProvider client={qc}>
            <UploadProvider>
              <DownloadProvider>
                <BrowserRouter basename="/ms-static/web">
                  <AppShell />
                </BrowserRouter>
              </DownloadProvider>
            </UploadProvider>
          </QueryClientProvider>
        </ErrorBoundary>
      </AntApp>
    </ConfigProvider>
  );
}
