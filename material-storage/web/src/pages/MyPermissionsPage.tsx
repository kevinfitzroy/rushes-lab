/**
 * 我的权限 — 总览页:列出当前 user 在所有项目里的有效角色 + pending 申请单。
 * 数据复用 GET /projects(my_roles 字段)+ GET /approvals?scope=self&status=approved。
 */
import { Segmented, Skeleton, Tag } from 'antd';
import { Link } from 'react-router-dom';
import { ChevronRight, ShieldCheck } from 'lucide-react';
import { useState } from 'react';
import dayjs from 'dayjs';
import 'dayjs/locale/zh-cn';
import relativeTime from 'dayjs/plugin/relativeTime';
import { useApprovals, useMe, useProjects } from '../api/hooks';
import { GrantCountdown } from '../components/GrantCountdown';

type RoleFilter = 'all' | 'admin' | 'uploader' | 'downloader';

/**
 * #115 角色蕴含规则(按 permission-model-v4 §5):
 * - admin ⊃ 全部权限
 * - upload / download / viewer 三轴**并列**,uploader 不蕴含 download
 * issue body 表格把 uploader 算入"我可下载的" 与 model 矛盾,本实现按 model 来。
 * 若 gatekeeper 验收后觉得 issue 的 implication 表才对,改这里 4 行即可。
 */
function passFilter(roles: string[], f: RoleFilter): boolean {
  if (f === 'all') return roles.length > 0;
  if (f === 'admin') return roles.includes('admin');
  if (f === 'uploader') return roles.includes('admin') || roles.includes('uploader');
  if (f === 'downloader') return roles.includes('admin') || roles.includes('downloader');
  return true;
}

dayjs.extend(relativeTime);
dayjs.locale('zh-cn');
import { MyRolesBadge } from './ProjectsPage';
import type { Project } from '../api/types';

export default function MyPermissionsPage() {
  const { data: me } = useMe();
  const { data: projects, isLoading } = useProjects();
  const { data: approvals } = useApprovals('self', 'approved');

  const [filter, setFilter] = useState<RoleFilter>('all');

  // 仅显示有效授权:my_roles 非空 OR 临时授权 approved
  const ownedAll: Project[] = (projects ?? []).filter(p => (p.my_roles ?? []).length > 0);
  const owned: Project[] = ownedAll.filter(p => passFilter(p.my_roles ?? [], filter));
  const visitorOnly: Project[] = (projects ?? []).filter(p => (p.my_roles ?? []).length === 0);

  return (
    <div className="ms-enter">
      <header style={{ marginBottom: 'var(--ms-sp-2xl)' }}>
        <div style={{
          fontSize: 10, letterSpacing: '0.08em', textTransform: 'uppercase',
          color: 'var(--ms-ink-subtle)', fontFamily: 'var(--ms-font-mono)',
          fontWeight: 500, marginBottom: 6,
        }}>Permissions · Overview</div>
        <h1 style={{
          margin: 0, fontFamily: 'var(--ms-font-display)',
          fontSize: 36, fontWeight: 500, letterSpacing: '-0.02em',
          color: 'var(--ms-ink)', lineHeight: 1.1,
        }}>我的权限</h1>
        <p style={{
          margin: '8px 0 0', fontSize: 13, color: 'var(--ms-ink-muted)',
        }}>
          {me ? <>当前 <span className="ms-mono">{me.name}</span></> : '—'}
          {me?.is_system_admin && (
            <Tag color="gold" style={{
              marginLeft: 10, padding: '0 8px', fontSize: 11,
              fontFamily: 'var(--ms-font-mono)', letterSpacing: '0.04em',
            }}>
              <ShieldCheck size={11} strokeWidth={2.2}
                           style={{ verticalAlign: -2, marginRight: 4 }} />
              SYSTEM ADMIN
            </Tag>
          )}
        </p>
      </header>

      {/* ── 临时授权 ─────────────────────────────────────────────────── */}
      {approvals && approvals.length > 0 && (
        <Section title="临时授权" count={approvals.length}
                 desc="审批通过后获得的有时效权限,过期后失效">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {approvals.map(a => {
              const decided = a.decided_at ? dayjs(a.decided_at) : null;
              const expires = (decided && a.duration_seconds)
                ? decided.add(a.duration_seconds, 'second')
                : null;
              return (
                <div key={a.id} style={{
                  padding: '12px 16px',
                  background: 'var(--ms-surface)',
                  border: '1px solid var(--ms-hairline)',
                  borderRadius: 'var(--ms-radius-md)',
                  display: 'flex', alignItems: 'center', gap: 12,
                }}>
                  <Tag color={a.action === 'access' ? 'blue' : 'green'} style={{
                    fontFamily: 'var(--ms-font-mono)', fontSize: 11,
                    margin: 0,
                  }}>
                    {a.action === 'access' ? 'ACCESS' : 'DOWNLOAD'}
                  </Tag>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="ms-mono" style={{
                      fontSize: 12, color: 'var(--ms-ink)',
                      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                    }}>
                      {a.target_type}:{a.target_id}
                    </div>
                    <div style={{
                      marginTop: 2, fontSize: 11, color: 'var(--ms-ink-subtle)',
                      display: 'flex', alignItems: 'center', gap: 10,
                    }}>
                      {/* #117 方案 B:统一接 GrantCountdown(vertical bar 视觉),不再裸文字 */}
                      {a.decided_at && (
                        <GrantCountdown
                          decidedAt={a.decided_at}
                          durationSeconds={a.duration_seconds}
                        />
                      )}
                      {expires && (
                        <span>到 {expires.format('YYYY-MM-DD HH:mm')}</span>
                      )}
                      {!expires && decided && (
                        <span>{decided.format('YYYY-MM-DD HH:mm')} 起</span>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </Section>
      )}

      {/* ── 直接 / 继承授权 ──────────────────────────────────────────── */}
      <Section title="项目角色"
               count={filter === 'all' ? ownedAll.length : `${owned.length}/${ownedAll.length}`}
               desc="通过个人、用户组或部门继承而来的角色">
        {/* #115 角色 filter — admin 蕴含全部;upload/download 按 model v4 §5 并列 */}
        {ownedAll.length > 0 && (
          <div style={{ marginBottom: 12 }}>
            <Segmented
              size="small"
              value={filter}
              onChange={(v) => setFilter(v as RoleFilter)}
              options={[
                { label: `全部 (${ownedAll.length})`, value: 'all' },
                { label: '我管理的', value: 'admin' },
                { label: '我可上传的', value: 'uploader' },
                { label: '我可下载的', value: 'downloader' },
              ]}
            />
          </div>
        )}
        {isLoading ? (
          <Skeleton active />
        ) : ownedAll.length === 0 ? (
          <Empty>你目前没有任何项目角色</Empty>
        ) : owned.length === 0 ? (
          <Empty>当前筛选下没有匹配的项目(共 {ownedAll.length} 个项目角色)</Empty>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {owned.map(p => <ProjectRow key={p.id} project={p} />)}
          </div>
        )}
      </Section>

      {/* ── 仅访客可见 ──────────────────────────────────────────────── */}
      {visitorOnly.length > 0 && (
        <Section title="仅访客可见" count={visitorOnly.length}
                 desc="public 项目 — 看得到列表,具体能否下载视 folder 设置而定">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {visitorOnly.map(p => (
              <Link key={p.id} to={`/projects/${p.id}`}
                    className="ms-card-hover"
                    style={{
                      padding: '8px 14px',
                      background: 'var(--ms-surface)',
                      border: '1px solid var(--ms-hairline-soft)',
                      borderRadius: 'var(--ms-radius-md)',
                      display: 'flex', alignItems: 'center', gap: 10,
                      fontSize: 12.5, color: 'var(--ms-ink-muted)',
                      textDecoration: 'none',
                    }}>
                <span style={{ flex: 1 }}>{p.name}</span>
                <span className="ms-mono" style={{
                  fontSize: 11, color: 'var(--ms-ink-subtle)',
                }}>{p.code}</span>
                <ChevronRight size={13} strokeWidth={1.8}
                              style={{ color: 'var(--ms-ink-subtle)' }} />
              </Link>
            ))}
          </div>
        </Section>
      )}
    </div>
  );
}

// ─── 子组件 ───────────────────────────────────────────────────────────────
function Section({
  title, count, desc, children,
}: { title: string; count?: number | string; desc?: string; children: React.ReactNode }) {
  return (
    <section style={{ marginBottom: 'var(--ms-sp-2xl)' }}>
      <div style={{
        marginBottom: 'var(--ms-sp-md)',
        display: 'flex', alignItems: 'baseline', gap: 10,
      }}>
        <h2 style={{
          margin: 0, fontFamily: 'var(--ms-font-display)',
          fontSize: 17, fontWeight: 500, letterSpacing: '-0.01em',
          color: 'var(--ms-ink)',
        }}>{title}</h2>
        {count !== undefined && (
          <span className="ms-mono" style={{
            fontSize: 11, color: 'var(--ms-ink-subtle)',
          }}>{count}</span>
        )}
        {desc && (
          <span style={{
            fontSize: 12, color: 'var(--ms-ink-subtle)',
            marginLeft: 'auto',
          }}>{desc}</span>
        )}
      </div>
      {children}
    </section>
  );
}

function ProjectRow({ project: p }: { project: Project }) {
  return (
    <Link to={`/projects/${p.id}`}
          className="ms-card-hover"
          style={{
            padding: '14px 16px',
            background: 'var(--ms-surface)',
            border: '1px solid var(--ms-hairline)',
            borderRadius: 'var(--ms-radius-md)',
            display: 'flex', alignItems: 'center', gap: 14,
            textDecoration: 'none', color: 'inherit',
          }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          display: 'flex', alignItems: 'center', gap: 8,
          fontSize: 14, fontWeight: 500, color: 'var(--ms-ink)',
        }}>
          <span style={{
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            minWidth: 0,
          }}>{p.name}</span>
          <span className="ms-mono" style={{
            fontSize: 11, color: 'var(--ms-ink-subtle)',
            flexShrink: 0,
          }}>{p.code}</span>
        </div>
        {p.description && (
          <div style={{
            marginTop: 4, fontSize: 12, color: 'var(--ms-ink-muted)',
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}>{p.description}</div>
        )}
      </div>
      <MyRolesBadge roles={p.my_roles || []} />
      <ChevronRight size={14} strokeWidth={1.8}
                    style={{ color: 'var(--ms-ink-subtle)', flexShrink: 0 }} />
    </Link>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      padding: '32px 16px', textAlign: 'center',
      fontSize: 13, color: 'var(--ms-ink-subtle)',
      border: '1px dashed var(--ms-hairline)',
      borderRadius: 'var(--ms-radius-md)',
    }}>{children}</div>
  );
}
