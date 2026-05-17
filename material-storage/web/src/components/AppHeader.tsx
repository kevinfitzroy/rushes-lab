/**
 * AppHeader — 品牌印记 + ⌘K 命令栏 + 用户头像。
 * 不用 antd Layout.Header / Menu,自由 flex layout 控制视觉密度。
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AutoComplete, Empty, Modal } from 'antd';
import { Search as SearchIcon, Bell, Inbox } from 'lucide-react';
import { useMe, useProjects } from '../api/hooks';
import { UserMenu } from './UserMenu';
import type { Me } from '../api/types';

interface Props { me: Me; }

export function AppHeader({ me }: Props) {
  const navigate = useNavigate();
  const [cmdOpen, setCmdOpen] = useState(false);
  const isMac = useMemo(
    () => typeof navigator !== 'undefined' && /Mac/.test(navigator.platform),
    [],
  );

  // ⌘K / Ctrl+K 全局
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setCmdOpen(true);
      }
      if (e.key === 'Escape') setCmdOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  return (
    <>
      <header
        style={{
          position: 'sticky',
          top: 0,
          zIndex: 50,
          display: 'flex',
          alignItems: 'center',
          gap: 'var(--ms-sp-lg)',
          padding: '10px 24px',
          background: 'rgba(255, 255, 255, 0.85)',
          backdropFilter: 'saturate(180%) blur(20px)',
          WebkitBackdropFilter: 'saturate(180%) blur(20px)',
          borderBottom: '1px solid var(--ms-hairline)',
          height: 56,
        }}
      >
        {/* ── 品牌印记 ───────────────────────────────────────── */}
        <Brand onClick={() => navigate('/')} />

        {/* ── 导航 chip(简化为按钮)──────────────────────── */}
        <nav style={{ display: 'flex', alignItems: 'center', gap: 2, marginLeft: 'var(--ms-sp-md)' }}>
          <NavChip to="/" label="项目" navigate={navigate} />
          <NavChip to="/approvals" label="审批" navigate={navigate} />
        </nav>

        <div style={{ flex: 1 }} />

        {/* ── ⌘K 命令栏触发器 ─────────────────────────────── */}
        <button
          onClick={() => setCmdOpen(true)}
          aria-label="搜索 / 命令"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 8,
            height: 32,
            padding: '0 12px 0 10px',
            background: 'var(--ms-hairline-soft)',
            border: '1px solid var(--ms-hairline)',
            borderRadius: 'var(--ms-radius-md)',
            color: 'var(--ms-ink-muted)',
            fontSize: 12.5,
            fontFamily: 'inherit',
            cursor: 'pointer',
            minWidth: 220,
            transition: 'background var(--ms-dur-fast) var(--ms-ease)',
          }}
          onMouseEnter={e => (e.currentTarget.style.background = '#F0EEE9')}
          onMouseLeave={e => (e.currentTarget.style.background = 'var(--ms-hairline-soft)')}
        >
          <SearchIcon size={14} strokeWidth={1.8} />
          <span style={{ flex: 1, textAlign: 'left' }}>搜索项目 / 文件夹…</span>
          <kbd style={kbdStyle}>{isMac ? '⌘' : 'Ctrl'}</kbd>
          <kbd style={kbdStyle}>K</kbd>
        </button>

        {/* ── 简易通知占位 ─────────────────────────────────── */}
        <IconButton title="任务收件箱"><Inbox size={16} strokeWidth={1.8} /></IconButton>
        <IconButton title="通知"><Bell size={16} strokeWidth={1.8} /></IconButton>

        <UserMenu me={me} />
      </header>

      <CommandPalette open={cmdOpen} onClose={() => setCmdOpen(false)} />
    </>
  );
}

// ─── 品牌印记 ───────────────────────────────────────────────────────────────
function Brand({ onClick }: { onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 10,
        background: 'transparent',
        border: 0,
        padding: 0,
        cursor: 'pointer',
        color: 'var(--ms-ink)',
      }}
    >
      {/* 几何方块作 logo — 三层叠加给档案感 */}
      <span style={{
        position: 'relative',
        display: 'inline-block',
        width: 22,
        height: 22,
      }}>
        <span style={layerStyle('var(--ms-ink)', 14, 14, 0, 0)} />
        <span style={layerStyle('var(--ms-accent)', 14, 14, 4, 4, 0.85)} />
        <span style={layerStyle('var(--ms-emerald)', 14, 14, 8, 8, 0.7)} />
      </span>
      <span
        style={{
          fontFamily: 'var(--ms-font-display)',
          fontWeight: 500,
          fontSize: 16,
          letterSpacing: '-0.01em',
        }}
      >
        material<span style={{ color: 'var(--ms-accent)' }}>·</span>storage
      </span>
    </button>
  );
}

function layerStyle(bg: string, w: number, h: number, x: number, y: number, op = 1): React.CSSProperties {
  return {
    position: 'absolute',
    left: x, top: y,
    width: w, height: h,
    background: bg,
    opacity: op,
    borderRadius: 2,
  };
}

// ─── 导航 chip ─────────────────────────────────────────────────────────────
function NavChip({ to, label, navigate }: {
  to: string; label: string; navigate: (p: string) => void;
}) {
  const active = typeof window !== 'undefined'
    && (to === '/' ? window.location.pathname === '/ms-static/web/' || window.location.pathname === '/ms-static/web'
                   : window.location.pathname.includes(to));
  return (
    <button
      onClick={() => navigate(to)}
      style={{
        height: 32,
        padding: '0 12px',
        background: active ? 'var(--ms-hairline-soft)' : 'transparent',
        border: 0,
        borderRadius: 'var(--ms-radius-md)',
        color: active ? 'var(--ms-ink)' : 'var(--ms-ink-muted)',
        fontSize: 13,
        fontFamily: 'inherit',
        fontWeight: active ? 500 : 400,
        cursor: 'pointer',
        transition: 'all var(--ms-dur-fast) var(--ms-ease)',
      }}
      onMouseEnter={e => {
        if (!active) e.currentTarget.style.color = 'var(--ms-ink)';
      }}
      onMouseLeave={e => {
        if (!active) e.currentTarget.style.color = 'var(--ms-ink-muted)';
      }}
    >
      {label}
    </button>
  );
}

function IconButton({ children, title }: { children: React.ReactNode; title: string }) {
  return (
    <button
      title={title}
      aria-label={title}
      style={{
        width: 32, height: 32,
        display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
        background: 'transparent', border: 0, borderRadius: 'var(--ms-radius-md)',
        color: 'var(--ms-ink-muted)', cursor: 'pointer',
        transition: 'all var(--ms-dur-fast) var(--ms-ease)',
      }}
      onMouseEnter={e => {
        e.currentTarget.style.background = 'var(--ms-hairline-soft)';
        e.currentTarget.style.color = 'var(--ms-ink)';
      }}
      onMouseLeave={e => {
        e.currentTarget.style.background = 'transparent';
        e.currentTarget.style.color = 'var(--ms-ink-muted)';
      }}
    >
      {children}
    </button>
  );
}

const kbdStyle: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  minWidth: 18,
  height: 18,
  padding: '0 4px',
  fontSize: 10.5,
  fontFamily: 'var(--ms-font-mono)',
  color: 'var(--ms-ink-muted)',
  background: 'var(--ms-canvas)',
  border: '1px solid var(--ms-hairline)',
  borderRadius: 3,
};

// ─── 命令栏 (⌘K) ──────────────────────────────────────────────────────────
function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate();
  const { data: projects } = useProjects();
  const { data: me } = useMe();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [q, setQ] = useState('');

  useEffect(() => {
    if (open) setQ('');
  }, [open]);

  const options = useMemo(() => {
    const opts: { value: string; label: React.ReactNode; key: string; action: () => void }[] = [];
    const term = q.trim().toLowerCase();

    (projects || []).forEach(p => {
      if (!term || p.name.toLowerCase().includes(term) || p.code.toLowerCase().includes(term)) {
        opts.push({
          key: `p-${p.id}`,
          value: `项目 ${p.name}`,
          label: (
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '4px 0' }}>
              <span style={{
                width: 4, height: 16, borderRadius: 2,
                background: p.visibility === 'public' ? 'var(--ms-vis-public)'
                          : p.visibility === 'stealth' ? 'var(--ms-vis-stealth)'
                          : 'var(--ms-vis-private)',
              }} />
              <span style={{ flex: 1, color: 'var(--ms-ink)' }}>{p.name}</span>
              <span style={{ fontSize: 11, color: 'var(--ms-ink-subtle)',
                             fontFamily: 'var(--ms-font-mono)' }}>{p.code}</span>
            </div>
          ),
          action: () => navigate(`/projects/${p.id}`),
        });
      }
    });

    // 内置 actions
    const acts = [
      { kw: '审批 approvals', label: '前往·审批', go: () => navigate('/approvals') },
      { kw: '项目 projects', label: '前往·项目列表', go: () => navigate('/') },
    ];
    acts.forEach((a, i) => {
      if (!term || a.kw.includes(term) || a.label.includes(term)) {
        opts.push({
          key: `a-${i}`,
          value: a.label,
          label: <span style={{ color: 'var(--ms-ink-muted)' }}>↗ {a.label}</span>,
          action: a.go,
        });
      }
    });

    return opts;
  }, [projects, q, navigate]);

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      closable={false}
      width={560}
      destroyOnClose
      styles={{
        body: { padding: 0 },
        mask: { backdropFilter: 'blur(4px)' },
      }}
      className="ms-cmd-modal"
      afterOpenChange={(o) => { if (o) inputRef.current?.focus(); }}
    >
      <div style={{
        padding: '14px 18px',
        borderBottom: '1px solid var(--ms-hairline)',
        display: 'flex', alignItems: 'center', gap: 12,
      }}>
        <SearchIcon size={16} strokeWidth={1.8} style={{ color: 'var(--ms-ink-muted)' }} />
        <AutoComplete
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          ref={inputRef as any}
          value={q}
          onChange={setQ}
          options={options.map(o => ({ value: o.value, label: o.label, key: o.key }))}
          onSelect={(v) => {
            const opt = options.find(o => o.value === v);
            opt?.action();
            onClose();
          }}
          style={{ width: '100%' }}
          variant="borderless"
          placeholder="搜项目、文件夹,或键入命令…"
          allowClear={false}
          dropdownStyle={{ display: 'none' }}   // 让我们用下方自定义 list
        />
      </div>

      <div style={{
        maxHeight: 400,
        overflow: 'auto',
        padding: 6,
      }}>
        {options.length === 0 ? (
          <div style={{ padding: '32px 16px' }}>
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE}
                   description={<span style={{ color: 'var(--ms-ink-subtle)' }}>没找到匹配项</span>} />
          </div>
        ) : (
          options.map(opt => (
            <div
              key={opt.key}
              onClick={() => { opt.action(); onClose(); }}
              style={{
                padding: '10px 12px',
                cursor: 'pointer',
                borderRadius: 'var(--ms-radius-sm)',
                transition: 'background var(--ms-dur-fast) var(--ms-ease)',
              }}
              onMouseEnter={e => (e.currentTarget.style.background = 'var(--ms-hairline-soft)')}
              onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
            >
              {opt.label}
            </div>
          ))
        )}
      </div>

      <div style={{
        padding: '8px 14px',
        borderTop: '1px solid var(--ms-hairline)',
        background: 'var(--ms-canvas)',
        display: 'flex', alignItems: 'center', gap: 8,
        fontSize: 11, color: 'var(--ms-ink-subtle)',
      }}>
        <span>登录身份</span>
        <span style={{ fontFamily: 'var(--ms-font-mono)' }}>{me?.name}</span>
        <span style={{ marginLeft: 'auto' }}>
          <kbd style={kbdStyle}>↑</kbd> <kbd style={kbdStyle}>↓</kbd> 选择,
          <kbd style={{ ...kbdStyle, marginLeft: 4 }}>↵</kbd> 打开,
          <kbd style={{ ...kbdStyle, marginLeft: 4 }}>Esc</kbd> 关闭
        </span>
      </div>
    </Modal>
  );
}
