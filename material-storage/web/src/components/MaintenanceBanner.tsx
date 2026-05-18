import { Modal, Typography, Tag, Space, Alert, Result } from 'antd';
import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { http } from '../api/client';

type IssueBrief = { number: number; summary: string };
type Banner = {
  active: boolean;
  message?: string | null;
  issues?: IssueBrief[];
  started_at?: string | null;
  ends_at?: string | null;
};

const POLL_MS = 8_000;
const COMPLETE_TOAST_MS = 6_000;

/**
 * 维护通知 modal — deploy 时通过 redis 设置 banner,前端轮询拉到 active=true
 * 立刻弹不可关 modal;active 由 true→false 时显示 "升级完成" 几秒后自动关闭。
 * API 重启期间的网络错误**不**触发"完成"误判 — 用 lastKnownActive 兜底。
 */
export function MaintenanceBanner() {
  const { data, isError, isFetching } = useQuery<Banner>({
    queryKey: ['maintenance-banner'],
    queryFn: async () => (await http.get<Banner>('/api/v1/maintenance/banner')).data,
    refetchInterval: POLL_MS,
    refetchIntervalInBackground: true,
    retry: 0,
    staleTime: 0,
    // 静默失败 — 不弹 message.error;deploy 期间网络中断很正常
    meta: { suppressErrorMessage: true },
  });

  const lastKnownActiveRef = useRef(false);
  const [phase, setPhase] = useState<'idle' | 'maintaining' | 'just-finished'>('idle');
  const finishedTimerRef = useRef<number | null>(null);
  const [nowTick, setNowTick] = useState(Date.now());

  // 1 秒 tick 给倒计时
  useEffect(() => {
    if (phase !== 'maintaining') return;
    const t = window.setInterval(() => setNowTick(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, [phase]);

  // 状态机:监听 banner 变化
  useEffect(() => {
    // 网络错误 + 不知道之前状态 → 静默
    if (isError && !lastKnownActiveRef.current) return;
    // 网络错误 + 之前 active → 保持 maintaining,等下次成功响应
    if (isError && lastKnownActiveRef.current) return;
    if (!data) return;

    const wasActive = lastKnownActiveRef.current;
    const isActive = !!data.active;
    lastKnownActiveRef.current = isActive;

    if (isActive) {
      // 进入或保持维护中
      if (finishedTimerRef.current) {
        window.clearTimeout(finishedTimerRef.current);
        finishedTimerRef.current = null;
      }
      setPhase('maintaining');
    } else if (wasActive) {
      // 刚结束 — 显示"已恢复"几秒后关
      setPhase('just-finished');
      if (finishedTimerRef.current) window.clearTimeout(finishedTimerRef.current);
      finishedTimerRef.current = window.setTimeout(() => {
        setPhase('idle');
        finishedTimerRef.current = null;
      }, COMPLETE_TOAST_MS);
    } else {
      setPhase('idle');
    }
  }, [data, isError, isFetching]);

  useEffect(() => () => {
    if (finishedTimerRef.current) window.clearTimeout(finishedTimerRef.current);
  }, []);

  if (phase === 'idle') return null;

  if (phase === 'just-finished') {
    return (
      <Modal
        open
        closable={false}
        maskClosable={false}
        keyboard={false}
        footer={null}
        centered
        width={440}
      >
        <Result
          status="success"
          title="升级完成"
          subTitle="已恢复正常使用,如果之前的操作中断,请重新尝试一次。"
        />
      </Modal>
    );
  }

  // maintaining
  const endsAt = data?.ends_at ? new Date(data.ends_at).getTime() : null;
  const secsLeft = endsAt ? Math.max(0, Math.ceil((endsAt - nowTick) / 1000)) : null;
  const issues = data?.issues ?? [];
  const customMsg = data?.message?.trim();

  return (
    <Modal
      open
      closable={false}
      maskClosable={false}
      keyboard={false}
      footer={null}
      centered
      width={520}
      title={
        <Space size={8} align="center">
          <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%',
                         background: 'var(--ms-warning, #B45309)',
                         animation: 'ms-pulse 1.4s ease-in-out infinite' }} />
          <Typography.Text strong style={{ fontSize: 16 }}>系统升级中</Typography.Text>
        </Space>
      }
    >
      <style>{`
        @keyframes ms-pulse {
          0%, 100% { opacity: 1; transform: scale(1); }
          50% { opacity: 0.4; transform: scale(1.4); }
        }
      `}</style>

      <Typography.Paragraph style={{ marginBottom: 16 }}>
        {customMsg || '我们正在部署一次更新,通常 1 分钟内恢复。'}
        {secsLeft !== null && secsLeft > 0 && (
          <>
            {' '}
            <Typography.Text type="secondary">
              (预计 <strong>{secsLeft}</strong> 秒)
            </Typography.Text>
          </>
        )}
      </Typography.Paragraph>

      {issues.length > 0 && (
        <>
          <Typography.Text type="secondary" style={{ fontSize: 12, letterSpacing: 0.4 }}>
            本次解决
          </Typography.Text>
          <ul style={{ margin: '8px 0 16px', paddingLeft: 18, lineHeight: 1.9 }}>
            {issues.map((i) => (
              <li key={i.number}>
                <Tag color="orange" style={{ marginRight: 8 }}>#{i.number}</Tag>
                <span>{i.summary}</span>
              </li>
            ))}
          </ul>
        </>
      )}

      <Alert
        type="info"
        showIcon
        message="如果你正在上传或下载,可能会被打断 — 升级完成后请重试。"
      />
    </Modal>
  );
}
