import { Progress, Space, Tag } from 'antd';
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
    return <Tag color="green">永久</Tag>;
  }

  const decidedMs = new Date(decidedAt).getTime();
  const expireMs = decidedMs + durationSeconds * 1000;
  const remainSec = Math.max(0, (expireMs - now) / 1000);
  const pct = Math.max(0, Math.min(100, (remainSec / durationSeconds) * 100));
  const isExpired = remainSec <= 0;

  if (isExpired) return <Tag color="default">已过期</Tag>;

  const color = pct < 10 ? '#ff4d4f' : pct < 30 ? '#fa8c16' : '#52c41a';
  return (
    <Space direction="vertical" size={2} style={{ width: 130 }}>
      <Progress percent={pct} strokeColor={color} size="small" showInfo={false} />
      <span style={{ fontSize: 11, color: '#666' }}>{fmt(remainSec)} 剩余</span>
    </Space>
  );
}
