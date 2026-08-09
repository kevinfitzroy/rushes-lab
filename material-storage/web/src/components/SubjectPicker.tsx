/**
 * SubjectPicker — 统一选择"权限主体"。#154:飞书 department 轴写入下线(ADR-0007),
 * 仅剩两类:
 *   user        — 复用 UserPicker(多选)
 *   group       — GroupPicker(多选)
 *
 * value:  Subject[] — 每个 {kind: 'user'|'group', id: '<id>'}
 * 给上层 InviteModal:遍历 subjects 各自走对应 POST body
 *   user → {user_id, ...}   (users.id UUID,#148 起)
 *   group → {group_id, ...}
 */
import { Avatar, Select, Spin, Tabs, Tag } from 'antd';
import { Users as UsersIcon } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { http } from '../api/client';
import { UserPicker } from './UserPicker';
import type { Me } from '../api/types';

export type SubjectKind = 'user' | 'group';

export interface Subject {
  kind: SubjectKind;
  id: string;       // user.id (users.id UUID,#150 起) / group.id
  name?: string;    // 缓存显示用
}

interface Props {
  value: Subject[];
  onChange: (v: Subject[]) => void;
  me: Me;
  // 限制只允许某些 kind(例如 project admin 只允许 user/group)
  allowedKinds?: SubjectKind[];
}

const DEFAULT_KINDS: SubjectKind[] = ['user', 'group'];

export function SubjectPicker({
  value, onChange, me, allowedKinds = DEFAULT_KINDS,
}: Props) {
  const [tab, setTab] = useState<SubjectKind>(allowedKinds[0]);

  // 拆分 value(只 user 需 id 数组传给 UserPicker;group 在子组件内自取)
  const userIds = value.filter(s => s.kind === 'user').map(s => s.id);

  const setUsers = (ids: string[]) => {
    const rest = value.filter(s => s.kind !== 'user');
    onChange([...rest, ...ids.map(id => ({ kind: 'user' as const, id }))]);
  };
  const setGroups = (newSubs: Subject[]) => {
    const rest = value.filter(s => s.kind !== 'group');
    onChange([...rest, ...newSubs]);
  };

  const tabs = allowedKinds.map(k => ({
    key: k,
    label: (
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
        {k === 'user' && <span>用户</span>}
        {k === 'group' && <><UsersIcon size={12} strokeWidth={1.8} /><span>用户组</span></>}
      </span>
    ),
    children: (
      <div style={{ paddingTop: 4 }}>
        {k === 'user' && (
          <UserPicker
            value={userIds}
            onChange={(v) => setUsers(v as string[])}
            preset={[{ id: me.id, username: null, open_id: me.open_id,
                       union_id: me.union_id, name: me.name + '(自己)', email: me.email }]}
            placeholder="搜姓名 / 邮箱选用户"
          />
        )}
        {k === 'group' && (
          <GroupPicker value={value.filter(s => s.kind === 'group') as Subject[]}
                       onChange={setGroups} />
        )}
      </div>
    ),
  }));

  return (
    <div>
      <Tabs activeKey={tab} onChange={(k) => setTab(k as SubjectKind)} items={tabs}
            size="small" />

      {/* 已选汇总 — 跨 tab 都看得到 */}
      {value.length > 0 && (
        <div style={{
          marginTop: 8, padding: 8,
          background: 'var(--ms-hairline-soft)', borderRadius: 'var(--ms-radius-sm)',
          display: 'flex', flexWrap: 'wrap', gap: 4,
          fontSize: 11.5, color: 'var(--ms-ink-muted)',
        }}>
          <span style={{ marginRight: 4 }}>已选 {value.length} 项:</span>
          {value.map((s, i) => (
            <Tag key={`${s.kind}-${s.id}-${i}`}
                 closable onClose={() => onChange(value.filter((_, j) => j !== i))}
                 style={{ margin: 0 }}>
              {s.kind === 'user' && '👤'}
              {s.kind === 'group' && '🏷'}
              {' '}{s.name || s.id.slice(0, 12) + '…'}
            </Tag>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── GroupPicker(类 UserPicker 形态)───────────────────────────────────────
interface GroupBrief {
  id: string;
  name: string;
  description: string | null;
  member_count: number | null;
}

let debounceTimer: ReturnType<typeof setTimeout> | null = null;

function GroupPicker({
  value, onChange,
}: { value: Subject[]; onChange: (v: Subject[]) => void }) {
  const [options, setOptions] = useState<GroupBrief[]>([]);
  const [fetching, setFetching] = useState(false);
  const fetchRef = useRef(0);
  const briefById = useRef<Map<string, GroupBrief>>(new Map());

  useEffect(() => {
    options.forEach(g => briefById.current.set(g.id, g));
  }, [options]);

  const search = (q: string) => {
    if (debounceTimer) clearTimeout(debounceTimer);
    const tag = ++fetchRef.current;
    setFetching(true);
    debounceTimer = setTimeout(async () => {
      try {
        const { data } = await http.get<GroupBrief[]>('/api/v1/groups', {
          params: { q, limit: 30 },
        });
        if (tag === fetchRef.current) {
          setOptions(data);
          setFetching(false);
        }
      } catch {
        if (tag === fetchRef.current) { setOptions([]); setFetching(false); }
      }
    }, 250);
  };

  useEffect(() => { search(''); }, []); // prefetch

  const ids = value.map(s => s.id);
  return (
    <Select
      mode="multiple"
      value={ids}
      onChange={(v) => {
        const newIds = v as string[];
        // 保留已选 group(briefById 里有 name)+ 新加的
        onChange(newIds.map(id => ({
          kind: 'group' as const, id,
          name: briefById.current.get(id)?.name || id,
        })));
      }}
      placeholder="搜用户组名"
      showSearch filterOption={false} onSearch={search}
      notFoundContent={fetching ? <Spin size="small" /> : '无匹配项'}
      options={options.map(g => ({
        value: g.id,
        label: (
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '4px 0' }}>
            <Avatar size={22} style={{
              background: 'var(--ms-emerald)', color: 'var(--ms-canvas)',
              fontSize: 10, fontWeight: 500,
            }}>
              <UsersIcon size={12} strokeWidth={1.7} />
            </Avatar>
            <div style={{ minWidth: 0, flex: 1 }}>
              <div style={{ fontSize: 13, color: 'var(--ms-ink)' }}>{g.name}</div>
              <div style={{ fontSize: 10.5, color: 'var(--ms-ink-subtle)',
                            fontFamily: 'var(--ms-font-mono)' }}>
                {g.id.slice(0, 18)}…
                {g.member_count != null && ` · ${g.member_count} 人`}
              </div>
            </div>
          </div>
        ),
      }))}
      style={{ width: '100%' }}
    />
  );
}
