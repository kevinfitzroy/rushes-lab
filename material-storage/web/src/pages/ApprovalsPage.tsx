/**
 * 审批页 — timeline 列表风(b1 现代化重做)。
 * 每行:左侧状态色条 + 目标 / 动作 / 时长 + 理由(可折)+ 时间 + 操作。
 */
import { Alert, App, Button, Skeleton, Tabs } from 'antd';
import {
  Check, Clock, FileText, Folder as FolderIcon,
  HelpCircle, X, XCircle,
} from 'lucide-react';
import dayjs from 'dayjs';
import 'dayjs/locale/zh-cn';
import relativeTime from 'dayjs/plugin/relativeTime';
import {
  useApprovals, useApproveApproval, useRejectApproval,
} from '../api/hooks';
import type { Approval, ApprovalStatus } from '../api/types';
import { GrantCountdown } from '../components/GrantCountdown';
import { errorMessage } from '../api/client';

dayjs.extend(relativeTime);
dayjs.locale('zh-cn');

// 状态:色 + 标签 + 图标
const STATUS_META: Record<ApprovalStatus, {
  color: string; bg: string; label: string;
  Icon: React.ComponentType<{ size?: number; strokeWidth?: number }>;
}> = {
  pending:  { color: 'var(--ms-amber)',   bg: '#FEF3E8', label: '待审',
              Icon: Clock },
  approved: { color: 'var(--ms-emerald)', bg: 'var(--ms-emerald-soft)', label: '已批准',
              Icon: Check },
  rejected: { color: 'var(--ms-crimson)', bg: 'var(--ms-crimson-soft)', label: '已拒绝',
              Icon: XCircle },
  revoked:  { color: 'var(--ms-ink-muted)', bg: 'var(--ms-hairline-soft)', label: '已撤销',
              Icon: X },
  expired:  { color: 'var(--ms-ink-subtle)', bg: 'var(--ms-hairline-soft)', label: '已过期',
              Icon: Clock },
};

const TARGET_ICON: Record<string,
  React.ComponentType<{ size?: number; strokeWidth?: number }>> = {
  project: FolderIcon, sensitive_folder: FolderIcon, folder: FolderIcon, asset: FileText,
};

function ApprovalRow({
  a, scope, onApprove, onReject, approveLoading, rejectLoading,
}: {
  a: Approval; scope: 'self' | 'all';
  onApprove: () => void; onReject: () => void;
  approveLoading: boolean; rejectLoading: boolean;
}) {
  const meta = STATUS_META[a.status] || STATUS_META.pending;
  const TargetIcon = TARGET_ICON[a.target_type] || HelpCircle;
  const StatusIcon = meta.Icon;
  const canDecide = a.status === 'pending' && scope === 'all';

  return (
    <div style={{
      position: 'relative',
      display: 'grid',
      gridTemplateColumns: '1fr auto',
      gap: 20,
      padding: '18px 24px 18px 28px',
      background: 'var(--ms-surface)',
      border: '1px solid var(--ms-hairline)',
      borderRadius: 'var(--ms-radius-lg)',
      transition: 'border-color var(--ms-dur-fast) var(--ms-ease)',
    }}
    onMouseEnter={e => (e.currentTarget.style.borderColor = 'var(--ms-ink-subtle)')}
    onMouseLeave={e => (e.currentTarget.style.borderColor = 'var(--ms-hairline)')}
    >
      {/* 状态色条 */}
      <span style={{
        position: 'absolute', left: 0, top: 16, bottom: 16,
        width: 3, background: meta.color,
        borderRadius: '0 2px 2px 0',
      }} />

      {/* 左:内容 */}
      <div style={{ minWidth: 0 }}>
        {/* meta row */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          {/* status badge */}
          <span style={{
            display: 'inline-flex', alignItems: 'center', gap: 5,
            padding: '2px 8px',
            background: meta.bg, color: meta.color,
            borderRadius: 3,
            fontSize: 11, fontWeight: 500, letterSpacing: '0.01em',
          }}>
            <StatusIcon size={11} strokeWidth={2.4} />
            {meta.label}
          </span>
          {/* target type */}
          <span style={{
            display: 'inline-flex', alignItems: 'center', gap: 5,
            fontSize: 11.5, color: 'var(--ms-ink-muted)',
          }}>
            <TargetIcon size={12} strokeWidth={1.7} />
            <span className="ms-mono">{a.target_type}</span>
          </span>
          {/* action */}
          <span style={{
            fontSize: 11.5, color: 'var(--ms-ink-muted)',
          }}>
            动作 <span className="ms-mono" style={{ color: 'var(--ms-ink)' }}>{a.action}</span>
            {a.duration_seconds ? (
              <> · <span className="ms-mono">{formatDuration(a.duration_seconds)}</span></>
            ) : (
              <> · 永久</>
            )}
          </span>
          <div style={{ flex: 1 }} />
          <span style={{
            fontSize: 11.5, color: 'var(--ms-ink-subtle)',
          }}>{dayjs(a.created_at).fromNow()}</span>
        </div>

        {/* 理由(主文)*/}
        <div style={{
          marginTop: 8,
          fontSize: 13, color: 'var(--ms-ink)', lineHeight: 1.55,
          display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical',
          overflow: 'hidden',
        }}>{a.reason}</div>

        {/* target id + grant countdown */}
        <div style={{
          marginTop: 10,
          display: 'flex', gap: 16, alignItems: 'center', flexWrap: 'wrap',
          fontSize: 11.5, color: 'var(--ms-ink-subtle)',
        }}>
          <span>
            target <span className="ms-mono">{a.target_id.slice(0, 8)}…</span>
          </span>
          {a.status === 'approved' && a.decided_at && (
            <span style={{
              padding: '1px 8px',
              background: 'var(--ms-emerald-soft)',
              color: 'var(--ms-emerald)',
              borderRadius: 3,
            }}>
              剩余 <GrantCountdown decidedAt={a.decided_at}
                                  durationSeconds={a.duration_seconds} />
            </span>
          )}
          {a.decision_note && (
            <span style={{ fontStyle: 'italic' }}>
              说明:{a.decision_note}
            </span>
          )}
        </div>
      </div>

      {/* 右:操作 */}
      {canDecide && (
        <div style={{ display: 'flex', gap: 6, alignSelf: 'center', flexShrink: 0 }}>
          <Button size="small" type="primary"
                  icon={<Check size={13} strokeWidth={2.4} />}
                  loading={approveLoading} onClick={onApprove}>批准</Button>
          <Button size="small" danger
                  icon={<X size={13} strokeWidth={2.4} />}
                  loading={rejectLoading} onClick={onReject}>拒绝</Button>
        </div>
      )}
    </div>
  );
}

function formatDuration(seconds: number): string {
  if (seconds < 3600) return `${Math.round(seconds / 60)} 分`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} 时`;
  return `${Math.round(seconds / 86400)} 天`;
}

function ApprovalList({ scope }: { scope: 'self' | 'all' }) {
  const { data, isLoading } = useApprovals(scope);
  const approve = useApproveApproval();
  const reject = useRejectApproval();
  const { message, modal } = App.useApp();

  if (isLoading) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {[0, 1, 2].map(i => (
          <div key={i} style={{
            padding: '20px 24px', background: 'var(--ms-surface)',
            border: '1px solid var(--ms-hairline)', borderRadius: 'var(--ms-radius-lg)',
          }}>
            <Skeleton active paragraph={{ rows: 1 }} />
          </div>
        ))}
      </div>
    );
  }

  if (!data || data.length === 0) {
    return (
      <div style={{
        marginTop: 40, padding: '60px 40px', textAlign: 'center',
        background: 'var(--ms-surface)', border: '1px dashed var(--ms-hairline)',
        borderRadius: 'var(--ms-radius-lg)',
      }}>
        <Clock size={32} strokeWidth={1.3}
               style={{ color: 'var(--ms-hairline)', marginBottom: 14 }} />
        <div style={{
          fontFamily: 'var(--ms-font-display)', fontSize: 16, fontWeight: 500,
          color: 'var(--ms-ink)', marginBottom: 6,
        }}>暂无审批记录</div>
        <p style={{ margin: 0, fontSize: 12.5, color: 'var(--ms-ink-muted)' }}>
          {scope === 'self' ? '你的申请都会出现在这里' : '待你审批的项会出现在这里'}
        </p>
      </div>
    );
  }

  return (
    <div className="ms-enter-stagger"
         style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {data.map(a => (
        <ApprovalRow
          key={a.id} a={a} scope={scope}
          approveLoading={approve.isPending && approve.variables?.id === a.id}
          rejectLoading={reject.isPending && reject.variables?.id === a.id}
          onApprove={async () => {
            try {
              await approve.mutateAsync({ id: a.id });
              message.success('已批准');
            } catch (e) { message.error(errorMessage(e)); }
          }}
          onReject={() => modal.confirm({
            title: '确认拒绝?',
            content: '请告知申请人原因(可选)',
            onOk: async () => {
              try { await reject.mutateAsync({ id: a.id }); message.info('已拒绝'); }
              catch (e) { message.error(errorMessage(e)); }
            },
          })}
        />
      ))}
    </div>
  );
}

export default function ApprovalsPage() {
  return (
    <div className="ms-enter">
      <div style={{ marginBottom: 'var(--ms-sp-xl)' }}>
        <h1 style={{
          margin: 0,
          fontFamily: 'var(--ms-font-display)',
          fontSize: 32, fontWeight: 500, letterSpacing: '-0.02em',
          color: 'var(--ms-ink)', lineHeight: 1.1,
        }}>审批</h1>
        <p style={{ margin: '8px 0 0', fontSize: 13, color: 'var(--ms-ink-muted)' }}>
          权限申请与决策记录
        </p>
      </div>

      {/* #111 修复:删掉"新建申请"按钮,因为它要求 user 手填 36 位 UUID 无法获取。
          发起申请的入口收敛到资源页(项目 / 文件夹卡片旁的「申请权限」按钮 → RequestAccessModal)。 */}
      <Alert
        type="info"
        showIcon
        message="如需发起新申请,请到具体的项目 / 文件夹页面,点资源旁边的「申请权限」按钮。"
        style={{ marginBottom: 'var(--ms-sp-md)' }}
      />

      <Tabs
        defaultActiveKey="self"
        items={[
          { key: 'self', label: '我的申请', children: <ApprovalList scope="self" /> },
          { key: 'all', label: '待我审批 / 全部(admin)', children: <ApprovalList scope="all" /> },
        ]}
      />
    </div>
  );
}
