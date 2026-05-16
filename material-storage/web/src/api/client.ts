/**
 * axios client — withCredentials 走 cookie session(prod);
 * VITE_DEV_USER_ID 设置时附加 X-User-Id header(dev,backend env=dev 才接)。
 */
import axios from 'axios';

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
  (err) => {
    if (err.response?.status === 401 && !window.location.pathname.startsWith('/login')) {
      const next = encodeURIComponent(window.location.pathname + window.location.search);
      window.location.href = `${apiBase}/api/v1/auth/login?next=${next}`;
    }
    return Promise.reject(err);
  }
);
