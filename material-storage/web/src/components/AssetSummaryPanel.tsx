/**
 * 右侧选中文件 summary。0/1/N 选时不同显示。
 */
import { Descriptions, Empty, Statistic, Tag, Typography } from 'antd';
import { FileOutlined } from '@ant-design/icons';
import type { Asset } from '../api/types';

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}

interface Props {
  selected: Asset[];
}

export function AssetSummaryPanel({ selected }: Props) {
  if (selected.length === 0) {
    return (
      <div style={{ padding: 24 }}>
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={<Typography.Text type="secondary">选中文件查看详情</Typography.Text>}
        />
      </div>
    );
  }

  if (selected.length === 1) {
    const a = selected[0];
    return (
      <div style={{ padding: 16 }}>
        <Typography.Title level={5} style={{ marginTop: 0 }}>
          <FileOutlined /> {a.filename}
        </Typography.Title>
        <Descriptions size="small" column={1} bordered styles={{ label: { width: 96 } }}>
          <Descriptions.Item label="ID"><code style={{ fontSize: 11 }}>{a.id}</code></Descriptions.Item>
          <Descriptions.Item label="大小">{fmtBytes(a.size_bytes)}</Descriptions.Item>
          <Descriptions.Item label="类型">{a.content_type ?? <Tag>未知</Tag>}</Descriptions.Item>
          <Descriptions.Item label="ETag">{a.etag ? <code style={{ fontSize: 11 }}>{a.etag.slice(0, 16)}…</code> : '—'}</Descriptions.Item>
          <Descriptions.Item label="bucket"><code style={{ fontSize: 11 }}>{a.minio_bucket}</code></Descriptions.Item>
          <Descriptions.Item label="key"><code style={{ fontSize: 11, wordBreak: 'break-all' }}>{a.minio_key}</code></Descriptions.Item>
          <Descriptions.Item label="version">{a.minio_version_id?.slice(0, 16) ?? '—'}</Descriptions.Item>
          <Descriptions.Item label="创建">{new Date(a.created_at).toLocaleString('zh-CN')}</Descriptions.Item>
        </Descriptions>
      </div>
    );
  }

  // 多选 → 汇总统计
  const totalBytes = selected.reduce((s, a) => s + a.size_bytes, 0);
  const types = new Map<string, number>();
  for (const a of selected) {
    const t = a.content_type ?? '未知';
    types.set(t, (types.get(t) ?? 0) + 1);
  }

  return (
    <div style={{ padding: 16 }}>
      <Typography.Title level={5} style={{ marginTop: 0 }}>已选 {selected.length} 个文件</Typography.Title>
      <Statistic title="总大小" value={fmtBytes(totalBytes)} />
      <Typography.Paragraph type="secondary" style={{ marginTop: 16 }}>类型分布</Typography.Paragraph>
      <div>
        {Array.from(types.entries()).map(([t, c]) => (
          <Tag key={t} style={{ marginBottom: 4 }}>{t} · {c}</Tag>
        ))}
      </div>
    </div>
  );
}
