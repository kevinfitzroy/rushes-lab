/**
 * #151 盲搜结果页 — /search?q=…
 * 后端已按 can_view 过滤(敏感素材零泄露);此处只做展示:
 * tag chips + 命中词高亮(文件名 / 备注 / 标签),点击跳转所在 folder。
 */
import { App, Button, Empty, Input, Skeleton, Tag } from 'antd';
import { FolderOpen, Search as SearchIcon, Tag as TagIcon } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useSearchAssets } from '../api/hooks';
import { AppBreadcrumb } from '../components/AppBreadcrumb';
import type { SearchResult } from '../api/types';

/** 把 text 里命中 q(忽略大小写)的子串用高亮 span 包起来。*/
function Highlight({ text, q }: { text: string; q: string }) {
  const t = text.toLowerCase();
  const needle = q.toLowerCase();
  const out: React.ReactNode[] = [];
  let i = 0;
  while (i < text.length) {
    const idx = t.indexOf(needle, i);
    if (idx < 0) {
      out.push(<span key={`t${i}`}>{text.slice(i)}</span>);
      break;
    }
    if (idx > i) out.push(<span key={`t${i}`}>{text.slice(i, idx)}</span>);
    out.push(
      <span key={`h${idx}`} style={{
        background: 'var(--ms-accent-soft)',
        color: 'var(--ms-accent)',
        borderRadius: 2,
        padding: '0 1px',
      }}>{text.slice(idx, idx + needle.length)}</span>,
    );
    i = idx + needle.length;
  }
  return <>{out}</>;
}

export default function SearchPage() {
  const [sp, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const { message } = App.useApp();
  // q 直接以 URL 为准 — ⌘K 跳 /search?q=… 也能驱动输入框,无需 effect 同步
  const q = sp.get('q') ?? '';
  const [debounced, setDebounced] = useState(q);

  // 300ms 防抖,避免每击键都打后端
  useEffect(() => {
    const t = setTimeout(() => setDebounced(q), 300);
    return () => clearTimeout(t);
  }, [q]);

  const { data: results, isLoading, isFetching } = useSearchAssets(debounced.trim() || null);

  const goFolder = (r: SearchResult) => {
    navigate(`/folders/${r.folder_id}`);
  };

  return (
    <div className="ms-enter" style={{ maxWidth: 900, margin: '0 auto' }}>
      <AppBreadcrumb />

      {/* 搜索框 */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 10,
        background: 'var(--ms-surface)',
        border: '1px solid var(--ms-hairline)',
        borderRadius: 'var(--ms-radius-lg)',
        padding: '4px 16px',
        boxShadow: 'var(--ms-shadow-sm)',
        marginTop: 16,
      }}>
        <SearchIcon size={16} strokeWidth={1.8} style={{ color: 'var(--ms-ink-muted)', flexShrink: 0 }} />
        <Input
          value={q}
          onChange={(e) => {
            const v = e.target.value;
            setSearchParams(v ? { q: v } : {}, { replace: true });
            if (v.trim() === '') setDebounced('');
          }}
          variant="borderless"
          placeholder="搜文件名 / 标签 / 备注 — 跨全部有权限的文件夹…"
          allowClear
          autoFocus
          onPressEnter={() => setDebounced(q)}
          style={{ fontSize: 15, padding: '10px 0' }}
        />
        <kbd style={{
          fontFamily: 'var(--ms-font-mono)', fontSize: 10.5,
          color: 'var(--ms-ink-subtle)', background: 'var(--ms-canvas)',
          border: '1px solid var(--ms-hairline)', borderRadius: 3, padding: '1px 5px',
        }}>Enter</kbd>
      </div>

      <div style={{ margin: '14px 2px', fontSize: 12.5, color: 'var(--ms-ink-muted)' }}>
        {debounced.trim() ? (
          isFetching ? <>搜索中…</> : <>找到 <span className="ms-mono">{results?.length ?? 0}</span> 个文件</>
        ) : (
          '输入关键词开始搜索;仅返回你有查看权限的文件夹内容。'
        )}
      </div>

      {!debounced.trim() ? null : isLoading ? (
        <Skeleton active paragraph={{ rows: 6 }} />
      ) : !results || results.length === 0 ? (
        <div style={{
          padding: '60px 20px', textAlign: 'center',
          background: 'var(--ms-surface)',
          border: '1px dashed var(--ms-hairline)',
          borderRadius: 'var(--ms-radius-lg)',
        }}>
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={<span style={{ color: 'var(--ms-ink-muted)' }}>
              没有命中「{debounced.trim()}」的文件<br />试试标签 / 文件名关键词
            </span>}
          />
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {results.map((r) => {
            const notes = r.notes?.trim();
            const labelHit = r.user_labels.filter(l => l.toLowerCase().includes(debounced.trim().toLowerCase()));
            return (
              <div
                key={r.id}
                onClick={() => goFolder(r)}
                style={{
                  background: 'var(--ms-surface)',
                  border: '1px solid var(--ms-hairline)',
                  borderRadius: 'var(--ms-radius-lg)',
                  padding: '14px 18px',
                  cursor: 'pointer',
                  transition: 'border-color var(--ms-dur-fast) var(--ms-ease), box-shadow var(--ms-dur-fast) var(--ms-ease)',
                }}
                onMouseEnter={e => {
                  e.currentTarget.style.borderColor = 'var(--ms-hairline-strong, #D8D5CE)';
                  e.currentTarget.style.boxShadow = 'var(--ms-shadow-sm)';
                }}
                onMouseLeave={e => {
                  e.currentTarget.style.borderColor = 'var(--ms-hairline)';
                  e.currentTarget.style.boxShadow = 'none';
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span style={{
                    flex: 1, minWidth: 0,
                    fontSize: 14.5, fontWeight: 500, color: 'var(--ms-ink)',
                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  }}>
                    <Highlight text={r.filename} q={debounced.trim()} />
                  </span>
                  <span style={{
                    fontSize: 11, color: 'var(--ms-ink-subtle)',
                    display: 'inline-flex', alignItems: 'center', gap: 4, flexShrink: 0,
                  }}>
                    <FolderOpen size={11} strokeWidth={1.8} />
                    {r.folder_name}
                  </span>
                  <span className="ms-mono" style={{
                    fontSize: 10.5, color: 'var(--ms-ink-subtle)', flexShrink: 0,
                    maxWidth: 140, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  }}>{r.project_name}</span>
                </div>

                {/* 标签 chips — 命中标签高亮 */}
                {(r.user_labels.length > 0 || notes) && (
                  <div style={{
                    marginTop: 8,
                    display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap',
                  }}>
                    {r.user_labels.length > 0 && (
                      <TagIcon size={11} strokeWidth={1.8} style={{ color: 'var(--ms-ink-subtle)', flexShrink: 0 }} />
                    )}
                    {r.user_labels.map((l) => (
                      <Tag
                        key={l}
                        style={{
                          marginInlineEnd: 0,
                          background: labelHit.includes(l) ? 'var(--ms-accent-soft)' : undefined,
                          color: labelHit.includes(l) ? 'var(--ms-accent)' : undefined,
                          borderColor: 'var(--ms-hairline)',
                        }}
                      >{l}</Tag>
                    ))}
                    {notes && (
                      <span style={{
                        fontSize: 12, color: 'var(--ms-ink-muted)',
                        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                        maxWidth: '60%', minWidth: 0, marginLeft: 4,
                      }}>
                        <Highlight text={notes} q={debounced.trim()} />
                      </span>
                    )}
                  </div>
                )}
              </div>
            );
          })}

          <div style={{ textAlign: 'center', padding: 12 }}>
            <Button type="text" size="small"
                    onClick={() => message.info('MVP 只返回前 50 条,继续输入更精确的关键词')}
                    style={{ color: 'var(--ms-ink-subtle)' }}>
              {results.length >= 50 ? '结果超过 50 条,MVP 截断 — 用更精确关键词缩小范围' : ''}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
