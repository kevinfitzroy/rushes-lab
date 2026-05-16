import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import { initFeishu } from './lib/feishu';

// 飞书 H5 jssdk 初始化(非 webview 自动跳过)
initFeishu().then((r) => {
  if (r.inWebview) console.info('[feishu]', r);
});

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
