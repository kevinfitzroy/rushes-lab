import { Button, Card, Col, Empty, Row, Skeleton, Space, Tag, Typography } from 'antd';
import { PlusOutlined, ProjectOutlined } from '@ant-design/icons';
import { Link, useNavigate } from 'react-router-dom';
import { useState } from 'react';
import { useMe, useProjects } from '../api/hooks';
import { NewProjectModal } from '../components/NewProjectModal';

const VIS = {
  public: { color: 'green', label: '公开' },
  private: { color: 'blue', label: '私有' },
  stealth: { color: 'volcano', label: '机密' },
} as const;

export default function ProjectsPage() {
  const { data, isLoading } = useProjects();
  const { data: me } = useMe();
  const [createOpen, setCreateOpen] = useState(false);
  const navigate = useNavigate();

  const header = (
    <div style={{ display: 'flex', alignItems: 'center', marginBottom: 16 }}>
      <Typography.Title level={3} style={{ margin: 0, flex: 1 }}>
        <Space>
          <ProjectOutlined />
          <span>项目</span>
          {data && <Typography.Text type="secondary" style={{ fontSize: 14 }}>共 {data.length}</Typography.Text>}
        </Space>
      </Typography.Title>
      {me && (
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
          新建项目
        </Button>
      )}
    </div>
  );

  if (isLoading) {
    return (
      <>
        {header}
        <Row gutter={[16, 16]}>
          {Array.from({ length: 3 }).map((_, i) => (
            <Col key={i} xs={24} sm={12} lg={8}><Card><Skeleton active /></Card></Col>
          ))}
        </Row>
      </>
    );
  }

  return (
    <>
      {header}
      {(!data || data.length === 0) ? (
        <Empty description="还没有可见项目 — 申请加入或新建" style={{ marginTop: 80 }}>
          {me && (
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
              新建项目
            </Button>
          )}
        </Empty>
      ) : (
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
      )}

      {me && (
        <NewProjectModal
          open={createOpen}
          onClose={() => setCreateOpen(false)}
          onCreated={(id) => navigate(`/projects/${id}`)}
          me={me}
        />
      )}
    </>
  );
}
