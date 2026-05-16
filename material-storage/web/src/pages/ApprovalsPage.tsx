import { App, Button, Form, Input, InputNumber, Modal, Select, Space, Table, Tabs, Tag } from 'antd';
import { useState } from 'react';
import { useApprovals, useApproveApproval, useCreateApproval, useRejectApproval } from '../api/hooks';
import type { Approval } from '../api/types';

const statusColor: Record<string, string> = {
  pending: 'gold',
  approved: 'green',
  rejected: 'red',
  revoked: 'volcano',
  expired: 'default',
};

function ApprovalTable({ scope }: { scope: 'self' | 'all' }) {
  const { data, isLoading } = useApprovals(scope);
  const approve = useApproveApproval();
  const reject = useRejectApproval();
  const { message } = App.useApp();

  const cols = [
    { title: 'ID', dataIndex: 'id', render: (v: string) => v.slice(0, 8) },
    { title: 'Target', render: (_: unknown, r: Approval) => `${r.target_type} ${r.target_id.slice(0, 8)}` },
    { title: 'Action', dataIndex: 'action', render: (v: string) => <Tag>{v}</Tag> },
    { title: 'Duration', dataIndex: 'duration_seconds', render: (v: number | null) => v ? `${v}s` : '永久' },
    { title: 'Reason', dataIndex: 'reason', ellipsis: true },
    { title: 'Status', dataIndex: 'status', render: (v: string) => <Tag color={statusColor[v]}>{v}</Tag> },
    { title: 'Created', dataIndex: 'created_at', render: (v: string) => new Date(v).toLocaleString() },
    {
      title: '操作',
      render: (_: unknown, r: Approval) =>
        r.status === 'pending' && scope === 'all' ? (
          <Space>
            <Button size="small" type="primary"
                    onClick={async () => { await approve.mutateAsync({ id: r.id }); message.success('已批准'); }}>
              批准
            </Button>
            <Button size="small" danger
                    onClick={async () => { await reject.mutateAsync({ id: r.id }); message.info('已拒绝'); }}>
              拒绝
            </Button>
          </Space>
        ) : null,
    },
  ];
  return <Table dataSource={data ?? []} rowKey="id" loading={isLoading} columns={cols} size="small" />;
}

function NewApprovalModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const create = useCreateApproval();
  const [form] = Form.useForm();
  const { message } = App.useApp();
  return (
    <Modal title="新建申请" open={open} onCancel={onClose}
           onOk={async () => {
             const v = await form.validateFields();
             await create.mutateAsync({
               target_type: v.target_type,
               target_id: v.target_id,
               action: v.action,
               duration_seconds: v.duration_seconds || undefined,
               reason: v.reason,
             });
             message.success('已提交');
             form.resetFields();
             onClose();
           }}
           confirmLoading={create.isPending}>
      <Form form={form} layout="vertical" initialValues={{ target_type: 'sensitive_folder', action: 'access' }}>
        <Form.Item name="target_type" label="目标类型" rules={[{ required: true }]}>
          <Select options={[
            { label: 'sensitive_folder(进入敏感目录)', value: 'sensitive_folder' },
            { label: 'asset(单文件下载)', value: 'asset' },
            { label: 'project(整项目临时下载)', value: 'project' },
          ]}/>
        </Form.Item>
        <Form.Item name="target_id" label="目标 ID(UUID)" rules={[{ required: true }]}>
          <Input />
        </Form.Item>
        <Form.Item name="action" label="动作" rules={[{ required: true }]}>
          <Select options={[
            { label: 'access(永久邀请,仅 sensitive_folder)', value: 'access' },
            { label: 'download(临时下载)', value: 'download' },
          ]}/>
        </Form.Item>
        <Form.Item name="duration_seconds" label="有效期(秒,留空=永久,access only)">
          <InputNumber min={60} max={365 * 24 * 3600} style={{ width: '100%' }} placeholder="86400 = 24h" />
        </Form.Item>
        <Form.Item name="reason" label="理由" rules={[{ required: true, min: 4 }]}>
          <Input.TextArea rows={3} />
        </Form.Item>
      </Form>
    </Modal>
  );
}

export default function ApprovalsPage() {
  const [openNew, setOpenNew] = useState(false);
  return (
    <div>
      <Tabs
        tabBarExtraContent={<Button type="primary" onClick={() => setOpenNew(true)}>新建申请</Button>}
        items={[
          { key: 'self', label: '我的申请', children: <ApprovalTable scope="self" /> },
          { key: 'all', label: '待我审批 / 全部(admin)', children: <ApprovalTable scope="all" /> },
        ]}
      />
      <NewApprovalModal open={openNew} onClose={() => setOpenNew(false)} />
    </div>
  );
}
