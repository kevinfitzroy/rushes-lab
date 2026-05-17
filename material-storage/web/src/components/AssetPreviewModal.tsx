/**
 * AssetPreviewModal — md / txt inline 预览(一期)。
 * 后续二期可加 docx (mammoth) + xlsx (sheetjs)。
 */
import { App, Modal, Spin } from 'antd';
import { useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Asset } from '../api/types';
import { http, errorMessage } from '../api/client';

interface Props {
  asset: Asset;
  open: boolean;
  onClose: () => void;
}

type Kind = 'markdown' | 'text' | 'unsupported';

function detectKind(a: Asset): Kind {
  const name = a.filename.toLowerCase();
  const ct = (a.content_type || '').toLowerCase();
  if (name.endsWith('.md') || ct.startsWith('text/markdown')) return 'markdown';
  if (name.endsWith('.txt') || ct === 'text/plain') return 'text';
  // text/* 兜底也按 text 处理(csv/log/json 看着也能用)
  if (ct.startsWith('text/')) return 'text';
  return 'unsupported';
}

export function isPreviewable(a: Asset): boolean {
  return detectKind(a) !== 'unsupported';
}

export function AssetPreviewModal({ asset, open, onClose }: Props) {
  const { message } = App.useApp();
  const [content, setContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const kind = detectKind(asset);

  useEffect(() => {
    if (!open) { setContent(null); return; }
    if (kind === 'unsupported') return;
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const { data } = await http.post<{ url: string }>(
          `/api/v1/assets/${asset.id}/download-link`, {},
        );
        // 直接 fetch presigned URL(跨 origin 但 GET 不带 cookie 没问题)
        const r = await fetch(data.url);
        if (!r.ok) throw new Error(`fetch ${r.status}`);
        const text = await r.text();
        if (!cancelled) setContent(text);
      } catch (e) {
        if (!cancelled) message.error(errorMessage(e, '预览加载失败'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [open, asset.id, kind, message]);

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      title={asset.filename}
      width="min(960px, 92vw)"
      styles={{ body: { maxHeight: '72vh', overflow: 'auto', padding: 24 } }}
      destroyOnClose
    >
      {loading && (
        <div style={{ padding: 60, textAlign: 'center' }}>
          <Spin />
        </div>
      )}
      {!loading && kind === 'unsupported' && (
        <div style={{
          padding: 40, textAlign: 'center',
          color: 'var(--ms-ink-muted)', fontSize: 13, lineHeight: 1.7,
        }}>
          此文件类型暂不支持在线预览。<br/>
          请下载后用本地软件打开。
        </div>
      )}
      {!loading && kind === 'text' && content !== null && (
        <pre style={{
          margin: 0, padding: 16,
          background: 'var(--ms-hairline-soft)',
          borderRadius: 'var(--ms-radius-sm)',
          fontSize: 12.5, lineHeight: 1.7,
          fontFamily: 'var(--ms-font-mono)',
          color: 'var(--ms-ink)',
          whiteSpace: 'pre-wrap', wordBreak: 'break-word',
        }}>{content}</pre>
      )}
      {!loading && kind === 'markdown' && content !== null && (
        <div className="ms-md-preview" style={{
          fontSize: 14, lineHeight: 1.75, color: 'var(--ms-ink)',
        }}>
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
        </div>
      )}
    </Modal>
  );
}
