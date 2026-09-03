import './styles/tokens.css';
import { App as AntApp, ConfigProvider, Spin, message as antMessage, theme } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { Suspense, lazy } from 'react';
import { useMe } from './api/hooks';
import { errorMessage } from './api/client';
import { AppHeader } from './components/AppHeader';
import { PersistentUploadDrawer } from './components/PersistentUploadDrawer';
import { UploadFloatingIndicator } from './components/UploadFloatingIndicator';
import { ErrorBoundary } from './components/ErrorBoundary';
import { MaintenanceBanner } from './components/MaintenanceBanner';
import { UploadProvider } from './lib/upload-store';
import { DownloadProvider } from './lib/download-store';

const ProjectsPage = lazy(() => import('./pages/ProjectsPage'));
const ProjectDetailPage = lazy(() => import('./pages/ProjectDetailPage'));
const FolderDetailPage = lazy(() => import('./pages/FolderDetailPage'));
const ApprovalsPage = lazy(() => import('./pages/ApprovalsPage'));
const DevLoginPage = lazy(() => import('./pages/DevLoginPage'));
const LoginPage = lazy(() => import('./pages/LoginPage'));
const ChangePasswordPage = lazy(() => import('./pages/ChangePasswordPage'));
const ShareLandingPage = lazy(() => import('./pages/ShareLandingPage'));
const RequestLinkLandingPage = lazy(() => import('./pages/RequestLinkLandingPage'));
const AdminAuditPage = lazy(() => import('./pages/AdminAuditPage'));
const AdminUsersPage = lazy(() => import('./pages/AdminUsersPage'));
const AdminGroupsPage = lazy(() => import('./pages/AdminGroupsPage'));
const MyPermissionsPage = lazy(() => import('./pages/MyPermissionsPage'));
const SearchPage = lazy(() => import('./pages/SearchPage'));
const NotificationsPage = lazy(() => import('./pages/NotificationsPage'));

const qc = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, refetchOnWindowFocus: false, retry: false } },
  queryCache: new QueryCache({
    onError: (err) => {
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 401 || status === 403) return;
      antMessage.error(errorMessage(err, '数据加载失败'));
    },
  }),
  mutationCache: new MutationCache({
    onError: (err) => {
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 401) return;
      antMessage.error(errorMessage(err, '操作失败'));
    },
  }),
});

const RouterRoutes = () => (
  <Suspense fallback={
    <div style={{ padding: 120, textAlign: 'center', color: 'var(--ms-ink-muted)' }}>
      <Spin />
    </div>
  }>
    <Routes>
      <Route path="/" element={<ProjectsPage />} />
      <Route path="/projects/:projectId" element={<ProjectDetailPage />} />
      <Route path="/projects/:projectId/folders/:folderId" element={<ProjectDetailPage />} />
      <Route path="/folders/:folderId" element={<FolderDetailPage />} />
      <Route path="/approvals" element={<ApprovalsPage />} />
      <Route path="/notifications" element={<NotificationsPage />} />
      <Route path="/my-permissions" element={<MyPermissionsPage />} />
      <Route path="/admin/audit" element={<AdminAuditPage />} />
      <Route path="/admin/users" element={<AdminUsersPage />} />
      <Route path="/admin/groups" element={<AdminGroupsPage />} />
      <Route path="/search" element={<SearchPage />} />
      <Route path="/s/:token" element={<ShareLandingPage />} />
      <Route path="/r/:token" element={<RequestLinkLandingPage />} />
      <Route path="/dev-login" element={<DevLoginPage />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/change-password" element={<ChangePasswordPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  </Suspense>
);

function AppShell() {
  const { data: me, isLoading, isError } = useMe();
  const location = useLocation();

  // #149: 本地登录 / 改密是独立页(无 AppShell),未登录时也放行(useLocation 为 basename 相对路径)
  const onAuthPage = location.pathname === '/login' || location.pathname === '/change-password';

  if (location.pathname === '/dev-login') return <RouterRoutes />;

  if (isLoading) {
    return (
      <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center',
                    background: 'var(--ms-canvas)' }}>
        <div style={{ textAlign: 'center', color: 'var(--ms-ink-muted)' }}>
          <Spin />
          <div style={{ marginTop: 12, fontSize: 13 }}>正在准备工作台</div>
        </div>
      </div>
    );
  }

  if (isError || !me) {
    // 登录/改密页自身放行(必须在弹回判断之前,否则 /login 上无限自跳重载)
    if (onAuthPage) return <RouterRoutes />;
    // #149: 未登录 → 本地登录页,带完整路径(next)登录后回跳原页
    const next = encodeURIComponent(window.location.pathname + window.location.search + window.location.hash);
    window.location.href = `/ms-static/web/login?next=${next}`;
    return null;
  }

  // #149: 已登录访问 /login → 回首页(首登强制改密则先去改密页)
  if (location.pathname === '/login') {
    return <Navigate to={me.must_change_password ? '/change-password' : '/'} replace />;
  }

  // #149: must_change_password 路由守卫 — 只放行改密页,其余一律强制跳转
  if (me.must_change_password && !onAuthPage) {
    return <Navigate to="/change-password" replace />;
  }

  return (
    <div style={{
      minHeight: '100vh',
      background: 'var(--ms-canvas)',
      color: 'var(--ms-ink)',
      display: 'flex',
      flexDirection: 'column',
    }}>
      <AppHeader me={me} />
      <main style={{
        flex: 1,
        padding: '32px 24px 80px',
        maxWidth: 1480,
        margin: '0 auto',
        width: '100%',
      }}>
        <RouterRoutes />
      </main>
      <PersistentUploadDrawer />
      <UploadFloatingIndicator />
    </div>
  );
}

export default function App() {
  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        algorithm: theme.defaultAlgorithm,
        token: {
          // typography
          fontFamily:
            "'Geist Sans', 'OPPO Sans', 'HarmonyOS Sans', system-ui, sans-serif",
          fontFamilyCode: "'JetBrains Mono', ui-monospace, 'SF Mono', monospace",
          fontSize: 14,
          fontSizeHeading1: 32,
          fontSizeHeading2: 24,

          // palette
          colorPrimary: '#C2410C',
          colorSuccess: '#047857',
          colorWarning: '#B45309',
          colorError: '#9F1239',
          colorInfo: '#475569',
          colorBgBase: '#FAFAF7',
          colorBgContainer: '#FFFFFF',
          colorBgElevated: '#FFFFFF',
          colorBgLayout: '#FAFAF7',
          colorTextBase: '#1A1A1A',
          colorTextSecondary: '#6B6B68',
          colorBorder: '#E8E6E1',
          colorBorderSecondary: '#F0EEE9',

          // shape
          borderRadius: 8,
          borderRadiusLG: 12,
          borderRadiusSM: 6,
          borderRadiusXS: 4,

          // padding(antd 内部 size)
          paddingSM: 12,
          padding: 20,
          paddingLG: 32,

          // motion
          motionDurationFast: '120ms',
          motionDurationMid: '180ms',
          motionEaseInOut: 'cubic-bezier(0.2, 0, 0, 1)',

          // shadow — 抑制默认重阴影 + hairline 描边
          boxShadow:
            '0 1px 2px rgba(26,26,26,0.04), 0 0 0 1px rgba(232,230,225,1)',
          boxShadowSecondary:
            '0 2px 8px rgba(26,26,26,0.06), 0 0 0 1px rgba(232,230,225,1)',
          boxShadowTertiary: 'none',
        },
        components: {
          Button: {
            controlHeight: 36,
            controlHeightLG: 44,
            controlHeightSM: 28,
            fontWeight: 500,
            primaryShadow: 'none',
            defaultShadow: 'none',
            dangerShadow: 'none',
          },
          Card: {
            paddingLG: 32,
            headerHeight: 56,
            headerHeightSM: 48,
            boxShadowTertiary: 'none',
          },
          Table: {
            headerBg: 'transparent',
            headerColor: '#6B6B68',
            headerSplitColor: 'transparent',
            rowHoverBg: '#FAFAF7',
            cellPaddingBlock: 14,
            borderColor: '#F0EEE9',
          },
          Layout: {
            headerBg: '#FFFFFF',
            headerHeight: 56,
            headerPadding: '0 24px',
            bodyBg: '#FAFAF7',
            siderBg: '#FFFFFF',
          },
          Menu: {
            itemBg: 'transparent',
            itemSelectedBg: '#FEE4D0',
            itemSelectedColor: '#C2410C',
            itemHoverBg: '#F5F3EE',
            itemPaddingInline: 16,
            itemHeight: 36,
            iconSize: 16,
            horizontalItemSelectedBg: 'transparent',
          },
          Tree: {
            directoryNodeSelectedBg: '#FEE4D0',
            directoryNodeSelectedColor: '#C2410C',
            nodeHoverBg: '#F5F3EE',
            nodeSelectedBg: '#FEE4D0',
            titleHeight: 32,
          },
          Tag: {
            defaultBg: '#F5F3EE',
            defaultColor: '#6B6B68',
          },
          Drawer: {
            paddingLG: 32,
          },
          Input: {
            controlHeight: 36,
            paddingInline: 12,
            activeShadow: '0 0 0 3px rgba(194,65,12,0.18)',
          },
          Modal: {
            paddingContentHorizontalLG: 32,
            paddingMD: 24,
          },
          Tabs: {
            inkBarColor: '#C2410C',
            itemSelectedColor: '#1A1A1A',
            itemColor: '#6B6B68',
            itemHoverColor: '#1A1A1A',
            titleFontSize: 14,
          },
        },
      }}>
      <AntApp>
        <ErrorBoundary>
          <QueryClientProvider client={qc}>
            <UploadProvider>
              <DownloadProvider>
                <BrowserRouter basename="/ms-static/web">
                  <MaintenanceBanner />
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
