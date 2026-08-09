import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';

// #154:飞书 H5 jssdk 初始化已随飞书下线移除(ADR-0007)

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
