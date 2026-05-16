import { Card, Empty, Spin, Tag, Typography } from 'antd';
import { Link } from 'react-router-dom';
import { useProjects } from '../api/hooks';

const visibilityColor: Record<string, string> = {
  public: 'green',
  private: 'blue',
  stealth: 'volcano',
};

export default function ProjectsPage() {
  const { data, isLoading } = useProjects();
  if (isLoading) return <Spin />;
  if (!data || data.length === 0) return <Empty description="暂无可见项目" />;

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 16 }}>
      {data.map((p) => (
        <Link to={`/projects/${p.id}`} key={p.id}>
          <Card hoverable title={p.name}
                extra={<Tag color={visibilityColor[p.visibility]}>{p.visibility}</Tag>}>
            <Typography.Text type="secondary" code>{p.code}</Typography.Text>
            <Typography.Paragraph ellipsis={{ rows: 2 }} style={{ marginTop: 8 }}>
              {p.description ?? '—'}
            </Typography.Paragraph>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              bucket: {p.minio_bucket}
            </Typography.Text>
          </Card>
        </Link>
      ))}
    </div>
  );
}
