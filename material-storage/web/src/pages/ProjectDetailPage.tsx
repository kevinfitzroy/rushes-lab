import { Button, Empty, List, Skeleton, Space, Tag, Typography } from 'antd';
import { LockOutlined, FolderOpenOutlined, KeyOutlined, ArrowRightOutlined } from '@ant-design/icons';
import { Link, useParams } from 'react-router-dom';
import { useState } from 'react';
import { useFolders, useProject } from '../api/hooks';
import { AppBreadcrumb } from '../components/AppBreadcrumb';
import { RequestAccessModal } from '../components/RequestAccessModal';

export default function ProjectDetailPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const { data: project } = useProject(projectId);
  const { data: folders, isLoading } = useFolders(projectId);
  const [applyFor, setApplyFor] = useState<{ id: string; name: string } | null>(null);

  // folder 列表分两组:可见的(普通 + 已邀请 sensitive),不可见的 sensitive(从 list 拿不到,这里不知道)
  // 业务侧:用户看不到的 sensitive folder 当然不知道存在,所以这里只列可见 folders。
  // 不可见的 sensitive 通过"全局申请入口"(顶部审批页)或管理员通知告知。

  const sortedFolders = folders ? [...folders].sort((a, b) => {
    // sensitive 在前(更突出邀请态),其次按名称
    if (a.is_sensitive !== b.is_sensitive) return a.is_sensitive ? -1 : 1;
    return a.name.localeCompare(b.name);
  }) : [];

  return (
    <div>
      <AppBreadcrumb />
      <Typography.Title level={3} style={{ marginTop: 0 }}>
        {project?.name ?? <Skeleton.Input active size="small" />}
        {project && (
          <Tag style={{ marginLeft: 12 }}
               color={project.visibility === 'public' ? 'green' : project.visibility === 'stealth' ? 'volcano' : 'blue'}>
            {project.visibility}
          </Tag>
        )}
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 24 }}>
        {project?.description ?? '—'} <Typography.Text code style={{ marginLeft: 8 }}>{project?.code}</Typography.Text>
      </Typography.Paragraph>

      {isLoading ? (
        <Skeleton active />
      ) : sortedFolders.length === 0 ? (
        <Empty description="此项目暂无可见文件夹(或都是 sensitive 待邀请)" />
      ) : (
        <List
          bordered
          dataSource={sortedFolders}
          renderItem={(f) => (
            <List.Item
              actions={[
                <Link to={`/folders/${f.id}`} key="open">
                  <Button type="primary" ghost icon={<ArrowRightOutlined />}>打开</Button>
                </Link>,
              ]}
            >
              <List.Item.Meta
                avatar={f.is_sensitive
                  ? <LockOutlined style={{ fontSize: 18, color: '#fa541c' }} />
                  : <FolderOpenOutlined style={{ fontSize: 18, color: '#1677ff' }} />}
                title={
                  <Space>
                    <Typography.Text strong>{f.name}</Typography.Text>
                    {f.is_sensitive && <Tag color="volcano">sensitive — 已邀请可见</Tag>}
                  </Space>
                }
                description={<Typography.Text type="secondary" code style={{ fontSize: 12 }}>{f.minio_prefix}</Typography.Text>}
              />
            </List.Item>
          )}
        />
      )}

      <div style={{ marginTop: 20, padding: 12, background: '#fafafa', borderRadius: 4 }}>
        <Space>
          <KeyOutlined />
          <Typography.Text type="secondary">
            没看到想要的 sensitive 目录?向项目管理员索取 folder UUID 后点击下面按钮申请。
          </Typography.Text>
          <Button size="small" onClick={() => {
            const fid = prompt('请输入 sensitive folder UUID');
            if (fid) setApplyFor({ id: fid, name: fid.slice(0, 8) + '…' });
          }}>申请 sensitive 目录访问</Button>
        </Space>
      </div>

      {applyFor && (
        <RequestAccessModal
          open
          onClose={() => setApplyFor(null)}
          targetId={applyFor.id}
          targetName={applyFor.name}
          targetType="sensitive_folder"
          defaultAction="access"
        />
      )}
    </div>
  );
}
