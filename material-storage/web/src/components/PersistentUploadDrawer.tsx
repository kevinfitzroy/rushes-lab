/**
 * 全局上传抽屉 — 挂在 App 顶层,任何页面通过 useUpload().open(folderId) 唤起。
 * 关闭只 hide UI,uppy 实例仍在 store,上传后台继续。
 */
import { Drawer } from 'antd';
import { Tags } from 'lucide-react';
import { useCallback, useEffect, useRef } from 'react';
import { useUpload } from '../lib/upload-store';

import '@uppy/core/dist/style.min.css';
import '@uppy/dashboard/dist/style.min.css';

export function PersistentUploadDrawer() {
  const { activeFolderId, close, getUppy, getAllUppies } = useUpload();
  const currentNode = useRef<HTMLDivElement | null>(null);

  const mountCb = useCallback((node: HTMLDivElement | null) => {
    currentNode.current = node;
    if (!node || !activeFolderId) return;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const u = getUppy(activeFolderId) as any;
    if (!u) return;

    // 清旧 Dashboard(目标 div 已无效)
    const existing = u.getPlugin('Dashboard');
    if (existing) u.removePlugin(existing);

    // dynamic import dashboard plugin
    void import('@uppy/dashboard').then(({ default: Dashboard }) => {
      // race:可能 mount node 已被新 node 覆盖
      if (currentNode.current !== node) return;
      u.use(Dashboard, {
        inline: true,
        target: node,
        height: 460,
        width: '100%',
        showProgressDetails: true,
        proudlyDisplayPoweredByUppy: false,
        note: '支持拖拽 / 多选;最大 5GB,16MB 分片;关闭抽屉不会中断,可后台跑',
      });
    });
  }, [activeFolderId, getUppy]);

  // close 时清所有 uppy 的 Dashboard plugin(div 已 unmount)
  useEffect(() => {
    if (activeFolderId) return;
    for (const u of getAllUppies().values()) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const p = (u as any).getPlugin('Dashboard');
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      if (p) (u as any).removePlugin(p);
    }
  }, [activeFolderId, getAllUppies]);

  return (
    <Drawer
      title={activeFolderId ? `上传到 folder ${activeFolderId.slice(0, 8)}…` : '上传'}
      open={!!activeFolderId}
      onClose={close}
      width="min(760px, 100vw)"
      maskClosable
      keyboard
      destroyOnClose={false}
    >
      {activeFolderId && <div ref={mountCb} style={{ minHeight: 460, width: '100%' }} />}

      {/* #151: 打标引导 — 上传完成后在列表选中文件打标,之后可跨文件夹盲搜 */}
      {activeFolderId && (
        <div style={{
          marginTop: 12,
          display: 'flex', alignItems: 'flex-start', gap: 8,
          padding: '10px 12px',
          background: 'var(--ms-canvas)',
          border: '1px solid var(--ms-hairline)',
          borderRadius: 'var(--ms-radius-sm)',
          fontSize: 12, color: 'var(--ms-ink-muted)', lineHeight: 1.6,
        }}>
          <Tags size={13} strokeWidth={1.8}
                style={{ color: 'var(--ms-accent)', flexShrink: 0, marginTop: 2 }} />
          <span>
            上传完成后,选中文件点「打标」加标签/备注(如<em>棚拍</em>、<em>VIP</em>),
            之后就能用 ⌘K 跨所有文件夹搜到它。
          </span>
        </div>
      )}
    </Drawer>
  );
}
