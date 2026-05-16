import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// 生产部署在 /ms-web/ 路径(nginx 反代),base 必须匹配
// nginx 已映射 /ms-static/* → ms-api /static/*(避开 console 占用的 /static/)
// 故 base = /ms-static/web/,build 输出到 ../api/app/static/web/(ms-api 容器一并发布)
export default defineConfig({
  plugins: [react()],
  base: '/ms-static/web/',
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8200',
      '/ms-static': 'http://localhost:8200',
    },
  },
  build: {
    outDir: '../api/app/static/web',
    emptyOutDir: true,
    sourcemap: false,
    chunkSizeWarningLimit: 1500,
  },
});
