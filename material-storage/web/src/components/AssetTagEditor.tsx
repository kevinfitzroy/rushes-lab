/**
 * #151 行内打标 — 标签 chips + 点击展开 Select mode="tags" 编辑。
 * 保存走 PATCH /assets/{id}/meta(user_labels);备注(notes)另走 NotesEditor。
 */
import { App, Select, Tag } from 'antd';
import { Check, Pencil } from 'lucide-react';
import { useRef, useState } from 'react';
import { errorMessage } from '../api/client';
import { useUpdateAssetMeta } from '../api/hooks';
import type { Asset } from '../api/types';

export function AssetTagEditor({ asset, stopPropagation = true }: {
  asset: Asset;
  /** 表格内使用时 true:点击编辑不冒泡到行选中。 */
  stopPropagation?: boolean;
}) {
  const meta = useUpdateAssetMeta();
  const { message } = App.useApp();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<string[]>(asset.user_labels ?? []);
  const selectRef = useRef<HTMLDivElement | null>(null);

  const labels = asset.user_labels ?? [];

  const save = async () => {
    setEditing(false);
    const next = [...new Set(draft.map(s => s.trim()).filter(Boolean))];
    if (JSON.stringify(next) === JSON.stringify(labels)) return;
    try {
      await meta.mutateAsync({ asset_id: asset.id, user_labels: next });
    } catch (e) {
      message.error(errorMessage(e, '标签保存失败'));
    }
  };

  const onClick = (e: React.MouseEvent) => {
    if (stopPropagation) e.stopPropagation();
    setDraft(asset.user_labels ?? []);
    setEditing(true);
    // focus Select 需要一帧后(展开中)
    setTimeout(() => selectRef.current?.querySelector('input')?.focus(), 0);
  };

  return (
    <div ref={selectRef} onClick={(e) => { if (editing && stopPropagation) e.stopPropagation(); }}>
      {editing ? (
        <div style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
          <Select
            mode="tags"
            value={draft}
            onChange={setDraft}
            placeholder="输入后回车添加…"
            style={{ minWidth: 160, maxWidth: 260 }}
            size="small"
            open
            autoFocus
            tokenSeparators={[',', '，']}
            onBlur={save}
            onKeyDown={(e) => {
              if (e.key === 'Escape') { setEditing(false); e.stopPropagation(); }
            }}
            options={(draft ?? []).map(d => ({ value: d, label: d }))}
            suffixIcon={null}
          />
          <button
            onClick={(e) => { e.stopPropagation(); void save(); }}
            title="保存标签"
            style={{
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
              width: 22, height: 22, border: 0, borderRadius: 4,
              background: 'var(--ms-emerald-soft)', color: 'var(--ms-emerald)',
              cursor: 'pointer', flexShrink: 0,
            }}
          ><Check size={12} strokeWidth={2.4} /></button>
        </div>
      ) : (
        <span onClick={onClick} title="编辑标签" style={{
          display: 'inline-flex', alignItems: 'center', gap: 4, flexWrap: 'wrap',
          cursor: 'pointer', maxWidth: 280, padding: '2px 0',
        }}>
          {labels.length === 0 && (
            <span style={{ fontSize: 12, color: 'var(--ms-ink-subtle)' }}>打标…</span>
          )}
          {labels.slice(0, 3).map(l => (
            <Tag key={l} style={{ marginInlineEnd: 0, fontSize: 11, lineHeight: '18px' }}>{l}</Tag>
          ))}
          {labels.length > 3 && (
            <span className="ms-mono" style={{ fontSize: 10.5, color: 'var(--ms-ink-subtle)' }}>
              +{labels.length - 3}
            </span>
          )}
          <Pencil size={11} strokeWidth={1.8} style={{ color: 'var(--ms-ink-subtle)' }} />
        </span>
      )}
    </div>
  );
}
