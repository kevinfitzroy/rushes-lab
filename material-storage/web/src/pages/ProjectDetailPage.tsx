import { Button, Empty, Modal, Form, Input, InputNumber, List, Space, Spin, Tag, Typography, App } from 'antd';
import { LockOutlined, FolderOpenOutlined } from '@ant-design/icons';
import { Link, useParams } from 'react-router-dom';
import { useState } from 'react';
import { useCreateApproval, useFolders, useProject } from '../api/hooks';

export default function ProjectDetailPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const { data: project } = useProject(projectId);
  const { data: folders, isLoading } = useFolders(projectId);
  const [applyTarget, setApplyTarget] = useState<{ id: string; name: string } | null>(null);
  const create = useCreateApproval();
  const { message } = App.useApp();
  const [form] = Form.useForm();

  if (isLoading) return <Spin />;

  return (
    <div>
      <Typography.Title level={3}>
        {project?.name} <Tag>{project?.code}</Tag>
      </Typography.Title>
      <Typography.Paragraph type="secondary">{project?.description}</Typography.Paragraph>

      <List
        bordered
        dataSource={folders ?? []}
        locale={{
          emptyText: (
            <Empty description="本项目没有可见 folder(可能 sensitive 待邀请)" />
          ),
        }}
        renderItem={(f) => (
          <List.Item
            actions={[
              <Link to={`/folders/${f.id}`} key="open">
                <Button type="link">打开</Button>
              </Link>,
            ]}
          >
            <List.Item.Meta
              avatar={f.is_sensitive ? <LockOutlined /> : <FolderOpenOutlined />}
              title={
                <Space>
                  <span>{f.name}</span>
                  {f.is_sensitive && <Tag color="volcano">sensitive</Tag>}
                </Space>
              }
              description={<Typography.Text type="secondary" code>{f.minio_prefix}</Typography.Text>}
            />
          </List.Item>
        )}
      />

      <div style={{ marginTop: 16 }}>
        <Button onClick={() => setApplyTarget({ id: projectId!, name: project?.name ?? '' })}>
          没有看到想要的 folder?发起 access 申请
        </Button>
      </div>

      <Modal
        title={`申请进入 sensitive folder(需 admin 批准)`}
        open={!!applyTarget}
        onCancel={() => setApplyTarget(null)}
        onOk={async () => {
          const vals = await form.validateFields();
          await create.mutateAsync({
            target_type: 'sensitive_folder',
            target_id: vals.target_id,
            action: 'access',
            duration_seconds: vals.duration_seconds || undefined,
            reason: vals.reason,
          });
          message.success('申请已提交');
          form.resetFields();
          setApplyTarget(null);
        }}
        confirmLoading={create.isPending}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="target_id" label="Sensitive Folder ID" rules={[{ required: true }]}>
            <Input placeholder="UUID" />
          </Form.Item>
          <Form.Item name="duration_seconds" label="有效期(秒,留空=永久)">
            <InputNumber min={60} style={{ width: '100%' }} placeholder="86400 = 24h" />
          </Form.Item>
          <Form.Item name="reason" label="申请理由" rules={[{ required: true, min: 4 }]}>
            <Input.TextArea rows={3} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
