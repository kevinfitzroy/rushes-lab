/**
 * 项目列表 — 卡片网格(b1 现代化重做)。
 * 卡片左侧 4px visibility 色块条 + Fraunces display 大标题 + mono code + meta row。
 */
import { Button, Skeleton, Tooltip } from 'antd';
import { Plus, Lock, Globe, EyeOff } from 'lucide-react';
import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import dayjs from 'dayjs';
import 'dayjs/locale/zh-cn';
import relativeTime from 'dayjs/plugin/relativeTime';
import { useMe, useProjects } from '../api/hooks';
import { NewProjectModal } from '../components/NewProjectModal';
import type { Project } from '../api/types';

dayjs.extend(relativeTime);
dayjs.locale('zh-cn');

const VIS_META: Record<string, {
  color: string; label: string;
  Icon: React.ComponentType<{ size?: number; strokeWidth?: number }>;
}> = {
  public:  { color: 'var(--ms-vis-public)',  label: '公开', Icon: Globe },
  private: { color: 'var(--ms-vis-private)', label: '私有', Icon: Lock },
  stealth: { color: 'var(--ms-vis-stealth)', label: '机密', Icon: EyeOff },
};

export default function ProjectsPage() {
  const { data, isLoading } = useProjects();
  const { data: me } = useMe();
  const [createOpen, setCreateOpen] = useState(false);
  const navigate = useNavigate();

  return (
    <div className="ms-enter">
      {/* 标题区:Display + 极简元信息 */}
      <div style={{
        display: 'flex', alignItems: 'baseline', justifyContent: 'space-between',
        gap: 24, marginBottom: 'var(--ms-sp-2xl)',
      }}>
        <div>
          <h1 style={{
            margin: 0,
            fontFamily: 'var(--ms-font-display)',
            fontSize: 36,
            fontWeight: 500,
            letterSpacing: '-0.02em',
            color: 'var(--ms-ink)',
            lineHeight: 1.1,
          }}>项目</h1>
          <p style={{
            margin: '8px 0 0',
            fontSize: 13,
            color: 'var(--ms-ink-muted)',
          }}>
            {data ? <>共 <span className="ms-mono">{data.length}</span> 个项目</>
                  : isLoading ? '加载中…' : '—'}
          </p>
        </div>
        {me && (
          <Tooltip title={me.is_system_admin ? '' : '仅系统管理员可创建项目'} placement="left">
            <Button
              type="primary"
              icon={<Plus size={15} strokeWidth={2.2} />}
              onClick={() => setCreateOpen(true)}
              disabled={!me.is_system_admin}
              style={{ height: 36, fontWeight: 500 }}
            >新建项目</Button>
          </Tooltip>
        )}
      </div>

      {isLoading ? (
        <Grid>
          {Array.from({ length: 6 }).map((_, i) => <SkeletonCard key={i} />)}
        </Grid>
      ) : (!data || data.length === 0) ? (
        <EmptyState onCreate={me?.is_system_admin ? () => setCreateOpen(true) : undefined} />
      ) : (
        <div className="ms-enter-stagger">
          <Grid>
            {data.map(p => <ProjectCard key={p.id} project={p} />)}
          </Grid>
        </div>
      )}

      {me && (
        <NewProjectModal
          open={createOpen}
          onClose={() => setCreateOpen(false)}
          onCreated={(id) => navigate(`/projects/${id}`)}
          me={me}
        />
      )}
    </div>
  );
}

function Grid({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))',
      gap: 'var(--ms-sp-xl)',
    }}>{children}</div>
  );
}

function ProjectCard({ project: p }: { project: Project }) {
  const vis = VIS_META[p.visibility] || VIS_META.private;
  const VisIcon = vis.Icon;
  return (
    <Link
      to={`/projects/${p.id}`}
      className="ms-card-hover"
      style={{
        position: 'relative',
        display: 'block',
        padding: '24px 24px 20px 28px',
        background: 'var(--ms-surface)',
        border: '1px solid var(--ms-hairline)',
        borderRadius: 'var(--ms-radius-lg)',
        textDecoration: 'none',
        color: 'inherit',
        overflow: 'hidden',
      }}
    >
      {/* visibility 色块条 */}
      <span style={{
        position: 'absolute',
        left: 0, top: 16, bottom: 16,
        width: 3,
        background: vis.color,
        borderRadius: '0 2px 2px 0',
      }} />

      <h2 style={{
        margin: 0,
        fontFamily: 'var(--ms-font-display)',
        fontSize: 20, fontWeight: 500,
        lineHeight: 1.25, letterSpacing: '-0.01em',
        color: 'var(--ms-ink)',
      }}>{p.name}</h2>

      <div style={{
        marginTop: 4,
        fontFamily: 'var(--ms-font-mono)',
        fontSize: 11.5,
        color: 'var(--ms-ink-subtle)',
      }}>{p.code}</div>

      <p style={{
        margin: '14px 0 0',
        fontSize: 13, lineHeight: 1.55,
        color: 'var(--ms-ink-muted)',
        minHeight: 40,
        display: '-webkit-box',
        WebkitLineClamp: 2,
        WebkitBoxOrient: 'vertical',
        overflow: 'hidden',
      }}>
        {p.description || (
          <span style={{ color: 'var(--ms-ink-subtle)', fontStyle: 'italic' }}>
            未填描述
          </span>
        )}
      </p>

      <div style={{
        margin: '18px -24px -20px -28px',
        padding: '14px 24px 0 28px',
        borderTop: '1px solid var(--ms-hairline-soft)',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        gap: 12,
        fontSize: 11.5,
      }}>
        <span style={{
          display: 'inline-flex', alignItems: 'center', gap: 6,
          color: vis.color, fontWeight: 500,
        }}>
          <VisIcon size={12} strokeWidth={1.8} />
          {vis.label}
        </span>
        <span style={{ color: 'var(--ms-ink-subtle)' }}>
          {dayjs(p.created_at).fromNow()}
        </span>
      </div>
    </Link>
  );
}

function SkeletonCard() {
  return (
    <div style={{
      padding: '24px 24px 20px 28px',
      background: 'var(--ms-surface)',
      border: '1px solid var(--ms-hairline)',
      borderRadius: 'var(--ms-radius-lg)',
    }}>
      <Skeleton active title={{ width: '60%' }}
                paragraph={{ rows: 2, width: ['100%', '70%'] }} />
    </div>
  );
}

function EmptyState({ onCreate }: { onCreate?: () => void }) {
  return (
    <div style={{
      marginTop: 80,
      padding: '60px 40px',
      textAlign: 'center',
      background: 'var(--ms-surface)',
      border: '1px dashed var(--ms-hairline)',
      borderRadius: 'var(--ms-radius-lg)',
    }}>
      <svg width="48" height="48" viewBox="0 0 48 48" style={{ marginBottom: 20 }}>
        <rect x="8" y="14" width="32" height="22" rx="2"
              fill="none" stroke="var(--ms-hairline)" strokeWidth="1.5" />
        <rect x="12" y="10" width="24" height="4" rx="1"
              fill="none" stroke="var(--ms-ink-subtle)" strokeWidth="1.5" />
        <line x1="14" y1="20" x2="34" y2="20" stroke="var(--ms-hairline)" strokeWidth="1" />
        <line x1="14" y1="25" x2="28" y2="25" stroke="var(--ms-hairline)" strokeWidth="1" />
        <line x1="14" y1="30" x2="22" y2="30" stroke="var(--ms-hairline)" strokeWidth="1" />
      </svg>
      <div style={{
        fontFamily: 'var(--ms-font-display)',
        fontSize: 18, fontWeight: 500,
        color: 'var(--ms-ink)', marginBottom: 8,
      }}>还没有可见项目</div>
      <p style={{
        margin: 0, fontSize: 13, color: 'var(--ms-ink-muted)',
        maxWidth: 320, marginInline: 'auto',
      }}>
        申请加入已有项目,或者点击下方按钮新建一个属于你的素材库。
      </p>
      {onCreate && (
        <Button type="primary" icon={<Plus size={15} strokeWidth={2.2} />}
                onClick={onCreate} style={{ marginTop: 24, height: 36 }}>
          新建项目
        </Button>
      )}
    </div>
  );
}
