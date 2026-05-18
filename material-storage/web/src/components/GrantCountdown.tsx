/**
 * GrantCountdown — 临时授权剩余时间 widget。
 *
 * #117 方案 B:去掉 emerald-soft chip 背景,改用左侧 2px 彩色 vertical bar
 * 暗示状态(emerald=safe / amber<30% / crimson<10%);跟 AdminAuditPage
 * EventRow 的 left stripe 视觉语言一致。剩余文字本身已表达进度,不再叠 Progress widget。
 */
import { Tag } from 'antd';
import { useEffect, useState } from 'react';

interface Props {
  decidedAt: string;
  durationSeconds: number | null;
}

function fmt(s: number): string {
  if (s < 60) return `${Math.floor(s)}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${Math.floor(s % 60)}s`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
  return `${Math.floor(s / 86400)}d ${Math.floor((s % 86400) / 3600)}h`;
}

export function GrantCountdown({ decidedAt, durationSeconds }: Props) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (durationSeconds == null) return; // 永久 grant 不计
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [durationSeconds]);

  if (durationSeconds == null) {
    return (
      <Tag color="default" style={{
        margin: 0, padding: '0 8px', fontSize: 11,
        fontFamily: 'var(--ms-font-mono)', letterSpacing: '0.04em',
      }}>永久</Tag>
    );
  }

  const decidedMs = new Date(decidedAt).getTime();
  const expireMs = decidedMs + durationSeconds * 1000;
  const remainSec = Math.max(0, (expireMs - now) / 1000);
  const pct = Math.max(0, Math.min(100, (remainSec / durationSeconds) * 100));
  const isExpired = remainSec <= 0;

  if (isExpired) {
    return (
      <Tag color="default" style={{
        margin: 0, padding: '0 8px', fontSize: 11,
        fontFamily: 'var(--ms-font-mono)', letterSpacing: '0.04em',
        color: 'var(--ms-ink-subtle)',
      }}>已过期</Tag>
    );
  }

  const color =
    pct < 10 ? 'var(--ms-crimson, #c4413f)' :
    pct < 30 ? 'var(--ms-amber, #b45309)' :
    'var(--ms-emerald, #047857)';

  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center',
      gap: 8,
      paddingLeft: 8,
      position: 'relative',
      fontSize: 12, lineHeight: '18px',
      color: 'var(--ms-ink-muted)',
    }}>
      <span style={{
        position: 'absolute', left: 0, top: 1, bottom: 1,
        width: 2, background: color,
        borderRadius: '0 2px 2px 0',
      }} />
      <span style={{ fontFamily: 'var(--ms-font-mono)', color: 'var(--ms-ink)' }}>
        {fmt(remainSec)}
      </span>
      <span style={{ fontSize: 11, color: 'var(--ms-ink-subtle)' }}>剩余</span>
    </span>
  );
}
