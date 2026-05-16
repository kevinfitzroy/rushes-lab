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
    if (err.response?.status === 401 && !window.location.pathname.startsWith('/login')) {
      // HashRouter 下需带 hash 完整路径回业务前端;否则 callback 跳 /(MinIO Console)
      const next = encodeURIComponent(window.location.pathname + window.location.search + window.location.hash);
      window.location.href = `${apiBase}/api/v1/auth/login?next=${next}`;
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
