/**
 * axios client — withCredentials 走 cookie session(prod);
 * VITE_DEV_USER_ID / localStorage 设置时附加 X-User-Id header(dev,backend env=dev 才接)。
 */
import axios, { AxiosError } from 'axios';

export const apiBase = (import.meta.env.VITE_API_BASE ?? '').replace(/\/$/, '');

const DEV_USER_KEY = 'ms_dev_user_id';
export const getDevUserId = (): string | null => {
  try { return localStorage.getItem(DEV_USER_KEY); } catch { return null; }
};
export const setDevUserId = (id: string | null) => {
  try { id ? localStorage.setItem(DEV_USER_KEY, id) : localStorage.removeItem(DEV_USER_KEY); } catch { /* ignore */ }
};

export const http = axios.create({
  baseURL: apiBase,
  withCredentials: true,
  timeout: 30_000,
});

http.interceptors.request.use((config) => {
  const devId = getDevUserId() ?? (import.meta.env.VITE_DEV_USER_ID as string | undefined);
  if (devId) {
    config.headers = config.headers ?? {};
    (config.headers as Record<string, string>)['X-User-Id'] = devId;
  }
  return config;
});

http.interceptors.response.use(
  (r) => r,
  (err: AxiosError) => {
    if (err.response?.status === 401) {
      // #149: 认证页(本地登录 / 改密 / dev)自身的 401 是业务响应(如密码错误),不跳转;
      // 其余页面 401(会话失效)→ 本地登录页。带 next 完整路径回业务前端
      // (注意 pathname 含 /ms-static/web basename,所以用 endsWith 判断)
      const path = window.location.pathname;
      const onAuthPage = path.endsWith('/login') || path.endsWith('/change-password')
        || path.endsWith('/dev-login');
      if (!onAuthPage) {
        const next = encodeURIComponent(path + window.location.search + window.location.hash);
        window.location.href = `/ms-static/web/login?next=${next}`;
      }
    }
    return Promise.reject(err);
  }
);

/** 从 axios error 抽 user-friendly message,优先取 detail。*/
export function errorMessage(err: unknown, fallback = '请求失败'): string {
  if (axios.isAxiosError(err)) {
    const d = err.response?.data as { detail?: string } | undefined;
    if (d?.detail) return d.detail;
    if (err.response?.status) return `${fallback}(HTTP ${err.response.status})`;
    if (err.message) return err.message;
  }
  return fallback;
}
