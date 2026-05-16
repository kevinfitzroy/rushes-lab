import { Card, Col, Empty, Row, Skeleton, Tag, Typography } from 'antd';
import { ProjectOutlined } from '@ant-design/icons';
import { Link } from 'react-router-dom';
import { useProjects } from '../api/hooks';

const VIS = {
  public: { color: 'green', label: '公开' },
  private: { color: 'blue', label: '私有' },
  stealth: { color: 'volcano', label: '机密' },
} as const;

export default function ProjectsPage() {
  const { data, isLoading } = useProjects();

  if (isLoading) {
    return (
      <Row gutter={[16, 16]}>
        {Array.from({ length: 3 }).map((_, i) => (
          <Col key={i} xs={24} sm={12} lg={8}><Card><Skeleton active /></Card></Col>
        ))}
      </Row>
    );
  }
  if (!data || data.length === 0) {
    return <Empty description="还没有可见项目 — 申请加入或联系管理员" style={{ marginTop: 80 }} />;
  }

  return (
    <Row gutter={[16, 16]}>
      {data.map((p) => {
        const vis = VIS[p.visibility as keyof typeof VIS] ?? { color: 'default', label: p.visibility };
        return (
          <Col key={p.id} xs={24} sm={12} lg={8}>
            <Link to={`/projects/${p.id}`}>
              <Card hoverable
                    title={<><ProjectOutlined /> {p.name}</>}
                    extra={<Tag color={vis.color}>{vis.label}</Tag>}>
                <Typography.Text code style={{ fontSize: 12 }}>{p.code}</Typography.Text>
                <Typography.Paragraph ellipsis={{ rows: 2 }} style={{ marginTop: 8, minHeight: 40 }}>
                  {p.description ?? '—'}
                </Typography.Paragraph>
                <div style={{ fontSize: 12, color: '#999' }}>
                  <div>bucket · <code>{p.minio_bucket}</code></div>
                  <div>创建 · {new Date(p.created_at).toLocaleDateString()}</div>
                </div>
              </Card>
            </Link>
          </Col>
        );
      })}
    </Row>
  );
}
