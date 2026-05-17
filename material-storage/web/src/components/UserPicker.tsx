/**
 * UserPicker — antd Select with autocomplete /api/v1/users?q=
 * 支持 multiple 或 single;value 是 open_id 数组(或单 string)。
 * 显示:头像首字 + name + 小字 open_id。
 */
import { Avatar, Select, Spin, type SelectProps } from 'antd';
import { useEffect, useMemo, useRef, useState } from 'react';
import { http } from '../api/client';

interface UserBrief {
  id: string;
  open_id: string;
  union_id: string | null;
  name: string;
  email: string | null;
}

interface Props {
  value?: string[] | string;     // open_id(s)
  onChange?: (v: string[] | string) => void;
  multiple?: boolean;
  placeholder?: string;
  disabled?: boolean;
  preset?: UserBrief[];          // 可注入预选 / 当前用户等
  size?: SelectProps['size'];
}

let debounceTimer: ReturnType<typeof setTimeout> | null = null;

export function UserPicker({
  value, onChange, multiple = true, placeholder = '搜姓名 / 邮箱 / open_id…',
  disabled, preset, size,
}: Props) {
  const [options, setOptions] = useState<UserBrief[]>([]);
  const [fetching, setFetching] = useState(false);
  const fetchRef = useRef(0);

  // 选中 user 的 brief 缓存(用于显示 tag 含 name,不止 open_id)
  const briefById = useRef<Map<string, UserBrief>>(new Map());
  useEffect(() => {
    if (preset) preset.forEach(u => briefById.current.set(u.open_id, u));
    options.forEach(u => briefById.current.set(u.open_id, u));
  }, [options, preset]);

  const search = (q: string) => {
    if (debounceTimer) clearTimeout(debounceTimer);
    const tag = ++fetchRef.current;
    setFetching(true);
    debounceTimer = setTimeout(async () => {
      try {
        const { data } = await http.get<UserBrief[]>('/api/v1/users', {
          params: { q, limit: 20 },
        });
        if (tag === fetchRef.current) {
          setOptions(data);
          setFetching(false);
        }
      } catch {
        if (tag === fetchRef.current) {
          setOptions([]);
          setFetching(false);
        }
      }
    }, 250);
  };

  useEffect(() => { search(''); /* prefetch */ }, []); // eslint-disable-line

  const opts = useMemo(() => {
    const list = [...options];
    if (preset) {
      for (const u of preset) {
        if (!list.find(x => x.open_id === u.open_id)) list.push(u);
      }
    }
    return list.map(u => ({
      value: u.open_id,
      label: <UserRow user={u} />,
    }));
  }, [options, preset]);

  return (
    <Select
      mode={multiple ? 'multiple' : undefined}
      value={value as unknown as never}
      onChange={onChange as never}
      placeholder={placeholder}
      disabled={disabled}
      size={size}
      showSearch
      filterOption={false}
      onSearch={search}
      notFoundContent={fetching ? <Spin size="small" /> : '无匹配'}
      options={opts}
      style={{ width: '100%' }}
      tagRender={(props) => {
        const u = briefById.current.get(props.value as string);
        return (
          <span style={{
            display: 'inline-flex', alignItems: 'center', gap: 6,
            margin: '2px 4px 2px 0', padding: '1px 8px 1px 2px',
            background: 'var(--ms-hairline-soft)',
            border: '1px solid var(--ms-hairline)',
            borderRadius: 'var(--ms-radius-sm)',
            fontSize: 12,
          }}>
            <Avatar size={18} style={{
              background: 'var(--ms-ink)', color: 'var(--ms-canvas)',
              fontSize: 10, fontFamily: 'var(--ms-font-display)',
            }}>{(u?.name || '?').slice(0, 1).toUpperCase()}</Avatar>
            <span>{u?.name || props.value}</span>
            <a onClick={(e) => { e.preventDefault(); props.onClose?.(); }}
               style={{ color: 'var(--ms-ink-muted)', cursor: 'pointer' }}>×</a>
          </span>
        );
      }}
    />
  );
}

function UserRow({ user }: { user: UserBrief }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 10, padding: '4px 0',
    }}>
      <Avatar size={24} style={{
        background: 'var(--ms-ink)', color: 'var(--ms-canvas)',
        fontSize: 11, fontFamily: 'var(--ms-font-display)', flexShrink: 0,
      }}>{(user.name || '?').slice(0, 1).toUpperCase()}</Avatar>
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{
          fontSize: 13, color: 'var(--ms-ink)',
          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        }}>{user.name}</div>
        <div style={{
          fontSize: 10.5, color: 'var(--ms-ink-subtle)',
          fontFamily: 'var(--ms-font-mono)',
          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        }}>
          {user.open_id.slice(0, 18)}…{user.email ? ` · ${user.email}` : ''}
        </div>
      </div>
    </div>
  );
}
