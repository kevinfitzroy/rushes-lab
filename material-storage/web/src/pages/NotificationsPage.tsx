/**
 * 通知中心页(#153)— 应用内通知列表。
 * 每行:kind chip + 标题/正文 + 时间;点击跳对应资源(link)并标已读。
 * 顶部:全部已读;空态引导。
 */
import { Button, Empty, Skeleton, Tag, Typography } from 'antd';
import { Bell, CheckCheck } from 'lucide-react';
import dayjs from 'dayjs';
import 'dayjs/locale/zh-cn';
import relativeTime from 'dayjs/plugin/relativeTime';
import { useNavigate } from 'react-router-dom';
import { useNotifications, useMarkNotificationsRead } from '../api/hooks';
import { NOTIFICATION_KIND_LABEL, tlabel } from '../lib/labels';
import type { NotificationItem } from '../api/types';

dayjs.extend(relativeTime);
dayjs.locale('zh-cn');

const KIND_COLOR: Record<string, string> = {
  approval_pending: 'orange',
  approval_decided: 'green',
  folder_invite: 'blue',
  share: 'purple',
};

function NotificationRow({
  n, onClick,
}: {
  n: NotificationItem; onClick: () => void;
}) {
  return (
    <div
      onClick={onClick}
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        gap: 12,
        padding: '14px 16px',
        cursor: n.link ? 'pointer' : 'default',
        background: n.read_at ? 'transparent' : 'var(--ms-hairline-soft)',
        borderRadius: 'var(--ms-radius-md)',
        transition: 'background var(--ms-dur-fast) var(--ms-ease)',
      }}
      onMouseEnter={e => { e.currentTarget.style.background = 'var(--ms-hairline-soft)'; }}
      onMouseLeave={e => {
        e.currentTarget.style.background = n.read_at ? 'transparent' : 'var(--ms-hairline-soft)';
      }}
    >
      {/* 未读指示点 */}
      <span style={{
        width: 8, height: 8, borderRadius: '50%', marginTop: 6, flexShrink: 0,
        background: n.read_at ? 'var(--ms-hairline)' : 'var(--ms-accent)',
      }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <Tag color={KIND_COLOR[n.kind] || 'default'} style={{ margin: 0 }}>
            {tlabel(n.kind, NOTIFICATION_KIND_LABEL)}
          </Tag>
          <Typography.Text strong style={{ fontSize: 13.5, color: 'var(--ms-ink)' }}>
            {n.title}
          </Typography.Text>
        </div>
        {n.body && (
          <div style={{
            marginTop: 4, fontSize: 12.5, lineHeight: 1.6,
            color: 'var(--ms-ink-muted)', whiteSpace: 'pre-line',
          }}>
            {n.body}
          </div>
        )}
        <div style={{ marginTop: 4, fontSize: 11.5, color: 'var(--ms-ink-subtle)' }}>
          {dayjs(n.created_at).fromNow()}
        </div>
      </div>
    </div>
  );
}

export default function NotificationsPage() {
  const navigate = useNavigate();
  const { data, isLoading } = useNotifications(100, 0);
  const markRead = useMarkNotificationsRead();

  const items = data?.items ?? [];
  const unreadCount = data?.unread_count ?? 0;

  const open = (n: NotificationItem) => {
    // 点击跳对应资源;link 是 web 站内路径(如 /approvals、/projects/...、/s/<token>)
    if (n.link) {
      const path = n.link.replace(/^\/ms-static\/web/, '') || '/';
      navigate(path);
    }
    if (!n.read_at) markRead.mutate({ ids: [n.id] });
  };

  return (
    <div style={{ maxWidth: 860, margin: '0 auto' }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20,
      }}>
        <Bell size={18} strokeWidth={1.8} color="var(--ms-ink-muted)" />
        <h1 style={{
          fontFamily: 'var(--ms-font-display)', fontWeight: 500,
          fontSize: 22, margin: 0, color: 'var(--ms-ink)',
        }}>
          通知中心
        </h1>
        <span style={{ fontSize: 12.5, color: 'var(--ms-ink-subtle)' }}>
          {unreadCount > 0 ? `${unreadCount} 条未读` : '没有未读'}
        </span>
        <div style={{ flex: 1 }} />
        {unreadCount > 0 && (
          <Button
            size="small"
            icon={<CheckCheck size={14} />}
            loading={markRead.isPending}
            onClick={() => markRead.mutate({ all: true })}
          >
            全部已读
          </Button>
        )}
      </div>

      {isLoading ? (
        <Skeleton active paragraph={{ rows: 6 }} />
      ) : items.length === 0 ? (
        <Empty
          description="暂无通知"
          style={{ marginTop: 80, color: 'var(--ms-ink-subtle)' }}
        />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {items.map(n => (
            <NotificationRow key={n.id} n={n} onClick={() => open(n)} />
          ))}
        </div>
      )}
    </div>
  );
}
