/**
 * 短链落地页 — /s/{token}(b1 现代化重做)。
 * 单卡片大封面 + sharer + meta + 大 CTA。asset 自动下载。
 */
import { Button, Result, Spin } from 'antd';
import {
  Calendar, CloudDownload, FileText, Folder as FolderIcon,
  Lock, User as UserIcon,
} from 'lucide-react';
import { useEffect, useRef } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import dayjs from 'dayjs';
import 'dayjs/locale/zh-cn';
import relativeTime from 'dayjs/plugin/relativeTime';
import { useResolveShare } from '../api/hooks';

dayjs.extend(relativeTime);
dayjs.locale('zh-cn');

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}

export default function ShareLandingPage() {
  const { token } = useParams<{ token: string }>();
  const navigate = useNavigate();
  const { data, isLoading, isError, error } = useResolveShare(token);
  const downloadTriggered = useRef(false);

  useEffect(() => {
    if (data?.kind === 'asset' && data.download_url && !downloadTriggered.current) {
      downloadTriggered.current = true;
      const a = document.createElement('a');
      a.href = data.download_url;
      a.download = data.asset?.filename ?? '';
      a.style.display = 'none';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    }
  }, [data]);

  if (isLoading) {
    return (
      <div style={{ padding: 120, textAlign: 'center', color: 'var(--ms-ink-muted)' }}>
        <Spin />
        <div style={{ marginTop: 12, fontSize: 13 }}>正在解析分享链接</div>
      </div>
    );
  }

  if (isError) {
    const status = (error as { response?: { status?: number } })?.response?.status;
    if (status === 404) {
      return (
        <Result
          status="404"
          title={<span style={{ fontFamily: 'var(--ms-font-display)' }}>链接已失效</span>}
          subTitle="可能已过期,或目标资源已被删除。可联系分享者重新生成。"
          extra={<Button type="primary" onClick={() => navigate('/')}>回到首页</Button>}
        />
      );
    }
    return (
      <Result status="error"
              title="加载失败"
              subTitle={String(error)}
              extra={<Button onClick={() => window.location.reload()}>重试</Button>} />
    );
  }
  if (!data) return null;

  return (
    <div className="ms-enter" style={{ maxWidth: 640, margin: '40px auto', padding: '0 12px' }}>
      {/* 上方说明 chip */}
      <div style={{
        display: 'inline-flex', alignItems: 'center', gap: 6,
        padding: '4px 10px',
        background: 'var(--ms-accent-soft)',
        color: 'var(--ms-accent)',
        borderRadius: 999,
        fontSize: 11, fontWeight: 500, letterSpacing: '0.02em',
        marginBottom: 16,
      }}>
        <span style={{
          width: 6, height: 6, borderRadius: '50%', background: 'var(--ms-accent)',
        }} />
        分享给你
      </div>

      {/* 主卡 */}
      <div style={{
        background: 'var(--ms-surface)',
        border: '1px solid var(--ms-hairline)',
        borderRadius: 'var(--ms-radius-xl)',
        overflow: 'hidden',
        boxShadow: 'var(--ms-shadow-md)',
      }}>
        {/* Hero — 大封面区:几何插画 */}
        <div style={{
          padding: '40px 32px 32px',
          background: data.kind === 'asset'
            ? 'linear-gradient(135deg, #FEF3E8 0%, #FAFAF7 60%)'
            : 'linear-gradient(135deg, #FEE4D0 0%, #FAFAF7 60%)',
          borderBottom: '1px solid var(--ms-hairline-soft)',
          position: 'relative',
          overflow: 'hidden',
        }}>
          {/* 背景几何 */}
          <span style={{
            position: 'absolute', right: -30, top: -30,
            width: 120, height: 120,
            border: '1px solid var(--ms-hairline)',
            borderRadius: '50%', opacity: 0.6,
          }} />
          <span style={{
            position: 'absolute', right: -60, top: -10,
            width: 160, height: 160,
            border: '1px solid var(--ms-hairline)',
            borderRadius: '50%', opacity: 0.4,
          }} />

          <div style={{
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            width: 56, height: 56,
            background: 'var(--ms-surface)',
            border: '1px solid var(--ms-hairline)',
            borderRadius: 'var(--ms-radius-md)',
            color: 'var(--ms-accent)',
            marginBottom: 16,
            position: 'relative',
            boxShadow: 'var(--ms-shadow-sm)',
          }}>
            {data.kind === 'asset'
              ? <FileText size={24} strokeWidth={1.5} />
              : <FolderIcon size={24} strokeWidth={1.5} />}
          </div>

          <h1 style={{
            margin: 0,
            fontFamily: 'var(--ms-font-display)',
            fontSize: 26, fontWeight: 500,
            lineHeight: 1.2, letterSpacing: '-0.01em',
            color: 'var(--ms-ink)',
            wordBreak: 'break-word',
            position: 'relative',
          }}>
            {data.kind === 'asset' ? data.asset?.filename : data.folder?.name}
          </h1>

          {data.kind === 'asset' && data.asset && (
            <div style={{
              marginTop: 8,
              fontFamily: 'var(--ms-font-mono)', fontSize: 12,
              color: 'var(--ms-ink-muted)',
              position: 'relative',
            }}>
              {fmtBytes(data.asset.size_bytes)}
              {data.asset.content_type && (
                <> · {data.asset.content_type}</>
              )}
            </div>
          )}

          {data.kind === 'folder' && data.folder?.is_sensitive && (
            <div style={{
              marginTop: 10,
              display: 'inline-flex', alignItems: 'center', gap: 4,
              padding: '2px 8px',
              background: 'var(--ms-accent-soft)', color: 'var(--ms-accent)',
              borderRadius: 3,
              fontSize: 10.5, fontWeight: 500, letterSpacing: '0.02em',
            }}>
              <Lock size={10} strokeWidth={2.2} />
              SENSITIVE FOLDER
            </div>
          )}
        </div>

        {/* Meta + CTA */}
        <div style={{ padding: '20px 28px 28px' }}>
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'auto 1fr',
            gap: '10px 14px',
            fontSize: 13,
            marginBottom: 24,
          }}>
            <MetaIcon><UserIcon size={13} strokeWidth={1.8} /></MetaIcon>
            <MetaText label="分享自" value={data.sharer_name ?? '(未知)'} />

            <MetaIcon><Calendar size={13} strokeWidth={1.8} /></MetaIcon>
            <MetaText
              label="有效期至"
              value={
                <>
                  {dayjs(data.expires_at).format('YYYY-MM-DD HH:mm')}
                  <span style={{
                    marginLeft: 8, color: 'var(--ms-ink-subtle)', fontSize: 12,
                  }}>({dayjs(data.expires_at).fromNow()})</span>
                </>
              }
            />
          </div>

          {/* 主 CTA */}
          {data.kind === 'asset' ? (
            <>
              <Button
                type="primary" size="large" block
                icon={<CloudDownload size={16} strokeWidth={2} />}
                href={data.download_url}
                download={data.asset?.filename}
                style={{ height: 48, fontSize: 14, fontWeight: 500 }}
              >
                下载到本地
              </Button>
              <p style={{
                margin: '12px 0 0', textAlign: 'center',
                fontSize: 11.5, color: 'var(--ms-ink-subtle)',
              }}>
                下载应已自动开始。未触发请点击上方按钮。
              </p>
            </>
          ) : (
            <Button
              type="primary" size="large" block
              icon={<FolderIcon size={16} strokeWidth={2} />}
              onClick={() => navigate(
                `/projects/${data.folder!.project_id}/folders/${data.folder!.id}`
              )}
              style={{ height: 48, fontSize: 14, fontWeight: 500 }}
            >
              打开文件夹
            </Button>
          )}
        </div>
      </div>

      {/* footer 小提示 */}
      <div style={{
        marginTop: 20, textAlign: 'center',
        fontSize: 11, color: 'var(--ms-ink-subtle)',
      }}>
        通过 material·storage 安全分享
      </div>
    </div>
  );
}

// ─── helpers ────────────────────────────────────────────────────────────────
function MetaIcon({ children }: { children: React.ReactNode }) {
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
      width: 26, height: 26,
      background: 'var(--ms-hairline-soft)',
      borderRadius: 'var(--ms-radius-sm)',
      color: 'var(--ms-ink-muted)',
      flexShrink: 0,
    }}>{children}</span>
  );
}

function MetaText({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <div style={{ fontSize: 11, color: 'var(--ms-ink-subtle)' }}>{label}</div>
      <div style={{ marginTop: 2, color: 'var(--ms-ink)' }}>{value}</div>
    </div>
  );
}
