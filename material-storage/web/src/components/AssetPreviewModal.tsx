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

type Kind = 'markdown' | 'text' | 'image' | 'pdf' | 'video' | 'unsupported';

const IMAGE_EXT = new Set([
  '.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.bmp', '.avif', '.ico',
]);

const VIDEO_EXT = new Set(['.mp4', '.mov', '.webm', '.m4v']);

function detectKind(a: Asset): Kind {
  const name = a.filename.toLowerCase();
  const ct = (a.content_type || '').toLowerCase();
  if (name.endsWith('.md') || ct.startsWith('text/markdown')) return 'markdown';
  if (name.endsWith('.txt') || ct === 'text/plain') return 'text';
  if (name.endsWith('.pdf') || ct === 'application/pdf') return 'pdf';
  if (ct.startsWith('image/')) return 'image';
  if (ct.startsWith('video/')) return 'video';
  const dot = name.lastIndexOf('.');
  if (dot >= 0 && IMAGE_EXT.has(name.slice(dot))) return 'image';
  if (dot >= 0 && VIDEO_EXT.has(name.slice(dot))) return 'video';
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
        // image / pdf / video 不 fetch body,直接给浏览器原生 viewer
        // (video 走浏览器原生 Range request,MinIO presign 支持;走 nginx 默认透传不剥 Range)
        // text/md 拉文本
        if (kind === 'image' || kind === 'pdf' || kind === 'video') {
          if (!cancelled) setContent(data.url);
        } else {
          const r = await fetch(data.url);
          if (!r.ok) throw new Error(`fetch ${r.status}`);
          const text = await r.text();
          if (!cancelled) setContent(text);
        }
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
      {!loading && kind === 'image' && content !== null && (
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          background: 'var(--ms-hairline-soft)',
          borderRadius: 'var(--ms-radius-sm)',
          minHeight: 200,
        }}>
          <img src={content} alt={asset.filename} style={{
            maxWidth: '100%', maxHeight: '65vh',
            objectFit: 'contain', display: 'block',
          }} />
        </div>
      )}
      {!loading && kind === 'pdf' && content !== null && (
        <iframe
          src={content}
          title={asset.filename}
          style={{
            width: '100%', height: '68vh',
            border: '1px solid var(--ms-hairline)',
            borderRadius: 'var(--ms-radius-sm)',
            background: 'var(--ms-hairline-soft)',
          }}
        />
      )}
      {!loading && kind === 'video' && content !== null && (
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          background: '#000',
          borderRadius: 'var(--ms-radius-sm)',
        }}>
          <video
            controls
            src={content}
            style={{
              width: '100%', maxHeight: '68vh',
              display: 'block', borderRadius: 'var(--ms-radius-sm)',
            }}
          />
        </div>
      )}
    </Modal>
  );
}
