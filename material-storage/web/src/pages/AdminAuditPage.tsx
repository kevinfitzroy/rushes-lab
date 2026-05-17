/**
 * /admin/audit — audit 后台(timeline + 过滤 + CSV 导出)。
 * 任意认证 user 可访问(PoC 简化,生产可加 admin enforce)。
 */
import { Button, DatePicker, Empty, Input, Pagination, Select, Skeleton, Tooltip } from 'antd';
import {
  ChevronRight, Clock, Download, Filter, Search as SearchIcon,
} from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import dayjs, { type Dayjs } from 'dayjs';
import 'dayjs/locale/zh-cn';
import relativeTime from 'dayjs/plugin/relativeTime';
import { http, apiBase } from '../api/client';

dayjs.extend(relativeTime);
dayjs.locale('zh-cn');

interface AuditEvent {
  id: string;
  event_type: string;
  event_time: string;
  actor_user_id: string | null;
  actor_name: string | null;
  actor_open_id: string | null;
  target_asset_id: string | null;
  target_project_id: string | null;
  target_minio_key: string | null;
  request_ip: string | null;
  details: Record<string, unknown>;
}

// 常用 event_type 预设(下拉)— 可以输自定义
const EVENT_TYPES = [
  '', 'upload', 'download', 'signed_url_issued',
  'approval_submitted', 'approval_state_changed', 'approval_notified',
  'access_denied',
  'project_created', 'project_member_added', 'project_member_removed',
  'folder_created', 'sensitive_folder_invited', 'sensitive_folder_revoked',
  'invite_notified', 'share_link_created', 'share_link_accessed',
];

const PAGE_SIZE = 30;

export default function AdminAuditPage() {
  const [filters, setFilters] = useState<{
    event_type: string;
    actor_open_id: string;
    range: [Dayjs, Dayjs] | null;
  }>({ event_type: '', actor_open_id: '', range: null });
  const [page, setPage] = useState(1);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const params = useMemo(() => {
    const p: Record<string, string> = {
      limit: String(PAGE_SIZE),
      offset: String((page - 1) * PAGE_SIZE),
    };
    if (filters.event_type) p.event_type = filters.event_type;
    if (filters.actor_open_id) p.actor_open_id = filters.actor_open_id;
    if (filters.range) {
      p.from = filters.range[0].toISOString();
      p.to = filters.range[1].toISOString();
    }
    return p;
  }, [filters, page]);

  const { data, isLoading } = useQuery({
    queryKey: ['audit', params],
    queryFn: async () => (await http.get<AuditEvent[]>('/api/v1/admin/audit', { params })).data,
  });

  const exportUrl = useMemo(() => {
    const u = new URLSearchParams();
    if (filters.event_type) u.set('event_type', filters.event_type);
    if (filters.actor_open_id) u.set('actor_open_id', filters.actor_open_id);
    if (filters.range) {
      u.set('from', filters.range[0].toISOString());
      u.set('to', filters.range[1].toISOString());
    }
    return `${apiBase}/api/v1/admin/audit/export.csv?${u}`;
  }, [filters]);

  return (
    <div className="ms-enter">
      {/* 页头 */}
      <div style={{
        display: 'flex', alignItems: 'baseline', justifyContent: 'space-between',
        gap: 24, marginBottom: 'var(--ms-sp-xl)',
      }}>
        <div>
          <h1 style={{
            margin: 0,
            fontFamily: 'var(--ms-font-display)',
            fontSize: 32, fontWeight: 500, letterSpacing: '-0.02em',
            color: 'var(--ms-ink)', lineHeight: 1.1,
          }}>审计</h1>
          <p style={{ margin: '8px 0 0', fontSize: 13, color: 'var(--ms-ink-muted)' }}>
            全量行为日志 / 可按 actor / event_type / 时间过滤 / CSV 导出
          </p>
        </div>
        <Button icon={<Download size={14} strokeWidth={2} />}
                href={exportUrl} target="_blank">
          导出 CSV
        </Button>
      </div>

      {/* 过滤栏 */}
      <div style={{
        display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center',
      }}>
        <span style={{
          display: 'inline-flex', alignItems: 'center', gap: 6,
          color: 'var(--ms-ink-muted)', fontSize: 12.5,
        }}>
          <Filter size={13} strokeWidth={2} /> 过滤
        </span>
        <Select
          value={filters.event_type}
          onChange={(v) => { setFilters({ ...filters, event_type: v }); setPage(1); }}
          style={{ minWidth: 220 }}
          showSearch
          allowClear
          placeholder="event_type(任意 / 选)"
          options={EVENT_TYPES.map(t => ({ value: t, label: t || '— 全部 —' }))}
        />
        <Input
          value={filters.actor_open_id}
          onChange={(e) => { setFilters({ ...filters, actor_open_id: e.target.value }); }}
          onPressEnter={() => setPage(1)}
          placeholder="actor open_id"
          prefix={<SearchIcon size={13} strokeWidth={1.8} style={{ color: 'var(--ms-ink-subtle)' }} />}
          style={{ width: 280 }}
        />
        <DatePicker.RangePicker
          value={filters.range}
          onChange={(v) => { setFilters({ ...filters, range: v as [Dayjs, Dayjs] | null }); setPage(1); }}
          showTime
        />
      </div>

      {/* 列表 */}
      {isLoading ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {[0, 1, 2, 3].map(i => (
            <div key={i} style={{
              padding: '16px 20px',
              background: 'var(--ms-surface)',
              border: '1px solid var(--ms-hairline)',
              borderRadius: 'var(--ms-radius-md)',
            }}>
              <Skeleton active title={{ width: '40%' }} paragraph={{ rows: 1 }} />
            </div>
          ))}
        </div>
      ) : !data || data.length === 0 ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE}
               description={<span style={{ color: 'var(--ms-ink-subtle)' }}>无匹配记录</span>}
               style={{ marginTop: 80 }} />
      ) : (
        <>
          <div className="ms-enter-stagger"
               style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {data.map(e => (
              <EventRow
                key={e.id} event={e}
                expanded={expanded.has(e.id)}
                onToggle={() => {
                  const next = new Set(expanded);
                  next.has(e.id) ? next.delete(e.id) : next.add(e.id);
                  setExpanded(next);
                }}
              />
            ))}
          </div>
          <div style={{ marginTop: 24, textAlign: 'center' }}>
            <Pagination
              current={page}
              pageSize={PAGE_SIZE}
              total={data.length === PAGE_SIZE ? page * PAGE_SIZE + 1 : (page - 1) * PAGE_SIZE + data.length}
              showSizeChanger={false}
              onChange={setPage}
            />
          </div>
        </>
      )}
    </div>
  );
}

// ─── EventRow ───────────────────────────────────────────────────────────────
function EventRow({
  event: e, expanded, onToggle,
}: { event: AuditEvent; expanded: boolean; onToggle: () => void }) {
  const color = eventColor(e.event_type);
  return (
    <div style={{
      position: 'relative',
      padding: '12px 16px 12px 22px',
      background: 'var(--ms-surface)',
      border: '1px solid var(--ms-hairline)',
      borderRadius: 'var(--ms-radius-md)',
      cursor: 'pointer',
      transition: 'border-color var(--ms-dur-fast) var(--ms-ease)',
    }}
    onClick={onToggle}
    onMouseEnter={e => (e.currentTarget.style.borderColor = 'var(--ms-ink-subtle)')}
    onMouseLeave={e => (e.currentTarget.style.borderColor = 'var(--ms-hairline)')}
    >
      <span style={{
        position: 'absolute', left: 0, top: 12, bottom: 12,
        width: 2, background: color,
        borderRadius: '0 2px 2px 0',
      }} />
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <ChevronRight size={14} strokeWidth={1.8}
                      style={{
                        color: 'var(--ms-ink-subtle)',
                        transform: expanded ? 'rotate(90deg)' : 'none',
                        transition: 'transform var(--ms-dur-fast) var(--ms-ease)',
                        flexShrink: 0,
                      }} />
        <span style={{
          fontFamily: 'var(--ms-font-mono)',
          fontSize: 11.5, color, fontWeight: 500,
          padding: '2px 8px', background: `${color}14`,
          borderRadius: 3,
        }}>{e.event_type}</span>
        <span style={{ fontSize: 13, color: 'var(--ms-ink)' }}>
          {e.actor_name || (
            <span style={{ color: 'var(--ms-ink-subtle)', fontStyle: 'italic' }}>系统</span>
          )}
        </span>
        <div style={{ flex: 1 }} />
        <Tooltip title={dayjs(e.event_time).format('YYYY-MM-DD HH:mm:ss')}>
          <span style={{ fontSize: 11.5, color: 'var(--ms-ink-subtle)',
                          display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            <Clock size={11} strokeWidth={1.8} />
            {dayjs(e.event_time).fromNow()}
          </span>
        </Tooltip>
      </div>

      {/* 元信息行 */}
      {!expanded && (
        <div style={{
          marginTop: 6, paddingLeft: 24,
          fontSize: 11.5, color: 'var(--ms-ink-muted)',
          display: 'flex', flexWrap: 'wrap', gap: 16,
        }}>
          {e.target_project_id && (
            <span>project <span className="ms-mono">{e.target_project_id.slice(0, 8)}…</span></span>
          )}
          {e.target_asset_id && (
            <span>asset <span className="ms-mono">{e.target_asset_id.slice(0, 8)}…</span></span>
          )}
          {e.request_ip && <span className="ms-mono">{e.request_ip}</span>}
        </div>
      )}

      {/* 展开:full details */}
      {expanded && (
        <div style={{
          marginTop: 10, paddingLeft: 24,
          fontFamily: 'var(--ms-font-mono)', fontSize: 11.5,
          color: 'var(--ms-ink-muted)',
        }}>
          {e.actor_open_id && <div>actor: {e.actor_open_id}</div>}
          {e.target_project_id && <div>project: {e.target_project_id}</div>}
          {e.target_asset_id && <div>asset: {e.target_asset_id}</div>}
          {e.target_minio_key && <div>key: {e.target_minio_key}</div>}
          {e.request_ip && <div>ip: {e.request_ip}</div>}
          <details open style={{ marginTop: 8 }}>
            <summary style={{ cursor: 'pointer', color: 'var(--ms-ink)', userSelect: 'none' }}>
              details
            </summary>
            <pre style={{
              marginTop: 6, padding: 10,
              background: 'var(--ms-canvas)', borderRadius: 'var(--ms-radius-sm)',
              fontSize: 10.5, overflow: 'auto', maxHeight: 320,
              border: '1px solid var(--ms-hairline-soft)',
            }}>{JSON.stringify(e.details, null, 2)}</pre>
          </details>
        </div>
      )}
    </div>
  );
}

// event_type → 颜色(粗类别)
function eventColor(et: string): string {
  if (et.startsWith('access_denied')) return 'var(--ms-crimson)';
  if (et.includes('approval')) return 'var(--ms-amber)';
  if (et.startsWith('share') || et.startsWith('signed_url')) return 'var(--ms-emerald)';
  if (et.startsWith('upload') || et.startsWith('download')) return 'var(--ms-accent)';
  if (et.includes('project') || et.includes('folder') || et.includes('invite'))
    return 'var(--ms-ink)';
  return 'var(--ms-ink-muted)';
}
