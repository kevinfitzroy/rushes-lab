/**
 * /r/{token} — request-link 落地页(#112 PR-2)。
 * 接收者点开链接后:
 *   1. 必须登录(BrowserRouter basename + apiBase login redirect)
 *   2. fetch token meta;若 receiver_open_id 限定且不匹配 → 显示 "此链接不是给你的"
 *   3. 否则显示资源信息 + 自动弹 RequestAccessModal,actions filter 按 allowed_actions
 *   4. modal 提交时带 via_link query param,backend 二次 enforce
 */
import { Button, Result, Spin } from 'antd';
import { FileText, Folder as FolderIcon, Lock, User as UserIcon } from 'lucide-react';
import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import dayjs from 'dayjs';
import 'dayjs/locale/zh-cn';
import relativeTime from 'dayjs/plugin/relativeTime';
import { useResolveRequestLink } from '../api/hooks';
import { RequestAccessModal } from '../components/RequestAccessModal';

dayjs.extend(relativeTime);
dayjs.locale('zh-cn');

const TARGET_TYPE_LABEL: Record<string, string> = {
  asset: '文件',
  folder: '文件夹',
  sensitive_folder: '敏感目录',
  project: '项目',
};

const TARGET_ICON: Record<string, React.ReactNode> = {
  asset: <FileText size={20} strokeWidth={1.6} />,
  folder: <FolderIcon size={20} strokeWidth={1.6} />,
  sensitive_folder: <Lock size={20} strokeWidth={1.6} />,
  project: <FolderIcon size={20} strokeWidth={1.6} />,
};

export default function RequestLinkLandingPage() {
  const { token } = useParams<{ token: string }>();
  const navigate = useNavigate();
  const { data, isLoading, isError, error } = useResolveRequestLink(token);
  const [modalOpen, setModalOpen] = useState(false);

  if (isLoading) {
    return (
      <div style={{ padding: 120, textAlign: 'center', color: 'var(--ms-ink-muted)' }}>
        <Spin />
        <div style={{ marginTop: 12, fontSize: 13 }}>正在解析申请链接</div>
      </div>
    );
  }

  if (isError) {
    const status = (error as { response?: { status?: number } })?.response?.status;
    return (
      <Result
        status={status === 404 ? '404' : 'error'}
        title={status === 404 ? '链接不存在或已过期' : '加载失败'}
        subTitle="如果你确认链接没拼错,可能已过期 — 请让生成链接的管理员重新生成。"
        extra={<Button type="primary" onClick={() => navigate('/')}>返回首页</Button>}
      />
    );
  }

  if (!data) return null;

  // receiver 限定但不是我
  if (data.receiver_restricted && !data.receiver_match) {
    return (
      <Result
        status="403"
        title="此申请链接不是发给你的"
        subTitle="生成链接的管理员限定了接收者。请确认你登录的账号与发链接的人指定的是同一个;
                   如果是,请联系管理员重新生成不限接收者的链接。"
        extra={<Button type="primary" onClick={() => navigate('/')}>返回首页</Button>}
      />
    );
  }

  const expiresAt = dayjs(data.expires_at);

  return (
    <div style={{ maxWidth: 640, margin: '0 auto', paddingTop: 'var(--ms-sp-2xl)' }}>
      <div style={{
        fontSize: 10, letterSpacing: '0.08em', textTransform: 'uppercase',
        color: 'var(--ms-ink-subtle)', fontFamily: 'var(--ms-font-mono)',
        fontWeight: 500, marginBottom: 6,
      }}>Request · Access</div>
      <h1 style={{
        margin: 0, fontFamily: 'var(--ms-font-display)',
        fontSize: 28, fontWeight: 500, letterSpacing: '-0.02em',
        color: 'var(--ms-ink)', lineHeight: 1.2,
      }}>申请权限</h1>
      <p style={{ margin: '8px 0 24px', fontSize: 13, color: 'var(--ms-ink-muted)' }}>
        点击下方按钮发起申请;<strong>不会直接获得权限</strong>,管理员审批后才生效。
      </p>

      <div style={{
        padding: 'var(--ms-sp-lg)',
        background: 'var(--ms-surface)',
        border: '1px solid var(--ms-hairline)',
        borderRadius: 'var(--ms-radius-lg)',
        marginBottom: 16,
      }}>
        <div style={{
          display: 'flex', alignItems: 'center', gap: 14, marginBottom: 14,
        }}>
          <div style={{
            width: 44, height: 44, flexShrink: 0,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            background: 'var(--ms-hairline-soft)',
            borderRadius: 'var(--ms-radius-md)',
            color: 'var(--ms-ink-muted)',
          }}>
            {TARGET_ICON[data.target_type] ?? <FileText size={20} strokeWidth={1.6} />}
          </div>
          <div style={{ minWidth: 0, flex: 1 }}>
            <div style={{
              fontSize: 11.5, color: 'var(--ms-ink-subtle)',
              fontFamily: 'var(--ms-font-mono)', letterSpacing: '0.04em',
              marginBottom: 3,
            }}>{TARGET_TYPE_LABEL[data.target_type] || data.target_type}</div>
            <div style={{
              fontSize: 16, fontWeight: 500, color: 'var(--ms-ink)',
              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            }}>{data.target_name || '(未命名)'}</div>
          </div>
        </div>

        <div style={{
          display: 'flex', flexWrap: 'wrap', gap: 16,
          paddingTop: 12, borderTop: '1px dashed var(--ms-hairline)',
          fontSize: 12, color: 'var(--ms-ink-muted)',
        }}>
          {data.inviter_name && (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
              <UserIcon size={12} strokeWidth={1.8} />
              来自 {data.inviter_name}
            </span>
          )}
          <span>可申请:{data.allowed_actions.map(a => a === 'access' ? '访问' : '下载').join(' / ')}</span>
          <span>有效期至 {expiresAt.format('YYYY-MM-DD HH:mm')}({expiresAt.fromNow(true)}后过期)</span>
        </div>
      </div>

      <Button type="primary" size="large" block onClick={() => setModalOpen(true)}>
        发起申请
      </Button>

      {/* RequestAccessModal 接受 allowedActions 约束 + viaLink token */}
      <RequestAccessModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        targetId={data.target_id}
        targetName={data.target_name || '(未命名)'}
        targetType={data.target_type}
        defaultAction={data.allowed_actions[0]}
        allowedActions={data.allowed_actions}
        viaLink={data.token}
      />
    </div>
  );
}
