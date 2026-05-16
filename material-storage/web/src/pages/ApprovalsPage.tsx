import { App, Button, Form, Grid, Input, InputNumber, Modal, Select, Space, Table, Tabs, Tag, Tooltip } from 'antd';
import { useState } from 'react';
import { useApprovals, useApproveApproval, useCreateApproval, useRejectApproval } from '../api/hooks';
import type { Approval } from '../api/types';
import { AppBreadcrumb } from '../components/AppBreadcrumb';
import { GrantCountdown } from '../components/GrantCountdown';
import { errorMessage } from '../api/client';

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
  const { message, modal } = App.useApp();
  const screens = Grid.useBreakpoint();
  const compact = !screens.lg;

  const cols = [
    { title: 'ID', dataIndex: 'id', render: (v: string) => <code>{v.slice(0, 8)}</code>, width: 90 },
    {
      title: '目标',
      render: (_: unknown, r: Approval) => (
        <Space direction="vertical" size={0}>
          <Tag>{r.target_type}</Tag>
          <code style={{ fontSize: 11 }}>{r.target_id.slice(0, 8)}…</code>
        </Space>
      ),
      width: 130,
    },
    {
      title: '动作',
      render: (_: unknown, r: Approval) => (
        <Space direction="vertical" size={0}>
          <Tag color={r.action === 'access' ? 'cyan' : 'geekblue'}>{r.action}</Tag>
          {r.duration_seconds && <span style={{ fontSize: 11, color: '#999' }}>{r.duration_seconds}s</span>}
          {r.duration_seconds == null && <span style={{ fontSize: 11, color: '#52c41a' }}>永久</span>}
        </Space>
      ),
      width: 100,
    },
    {
      title: '理由',
      dataIndex: 'reason',
      ellipsis: { showTitle: true },
      responsive: ['lg' as const],
    },
    {
      title: '状态',
      dataIndex: 'status',
      render: (v: string) => <Tag color={statusColor[v]}>{v}</Tag>,
      width: 90,
    },
    {
      title: 'grant 剩余',
      render: (_: unknown, r: Approval) =>
        r.status === 'approved' && r.decided_at
          ? <GrantCountdown decidedAt={r.decided_at} durationSeconds={r.duration_seconds} />
          : '—',
      width: 150,
    },
    {
      title: '提交时间',
      dataIndex: 'created_at',
      render: (v: string) => new Date(v).toLocaleString('zh-CN', { hour12: false }),
      responsive: ['md' as const],
      width: 160,
    },
    {
      title: '操作',
      fixed: 'right' as const,
      width: 140,
      render: (_: unknown, r: Approval) =>
        r.status === 'pending' && scope === 'all' ? (
          <Space size={4}>
            <Button size="small" type="primary"
                    loading={approve.isPending && approve.variables?.id === r.id}
                    onClick={async () => {
                      try {
                        await approve.mutateAsync({ id: r.id });
                        message.success('已批准');
                      } catch (e) { message.error(errorMessage(e)); }
                    }}>批准</Button>
            <Button size="small" danger
                    onClick={() => {
                      modal.confirm({
                        title: '确认拒绝?',
                        content: '请告知申请人原因(可选)',
                        onOk: async () => {
                          try { await reject.mutateAsync({ id: r.id }); message.info('已拒绝'); }
                          catch (e) { message.error(errorMessage(e)); }
                        },
                      });
                    }}>拒绝</Button>
          </Space>
        ) : null,
    },
  ];

  return (
    <Table dataSource={data ?? []} rowKey="id" loading={isLoading}
           columns={cols} size={compact ? 'small' : 'middle'}
           scroll={{ x: 900 }} pagination={{ pageSize: 20, hideOnSinglePage: true }} />
  );
}

function NewApprovalModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const create = useCreateApproval();
  const [form] = Form.useForm();
  const { message } = App.useApp();
  return (
    <Modal title="新建申请" open={open} onCancel={onClose} destroyOnClose
           onOk={async () => {
             try {
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
             } catch (e) {
               if ((e as { errorFields?: unknown }).errorFields) return;
               message.error(errorMessage(e));
             }
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
        <Form.Item name="target_id" label="目标 ID(UUID)" rules={[{ required: true, len: 36 }]}>
          <Input placeholder="00000000-0000-0000-0000-000000000000" />
        </Form.Item>
        <Form.Item name="action" label="动作" rules={[{ required: true }]}>
          <Select options={[
            { label: 'access(永久邀请,仅 sensitive_folder)', value: 'access' },
            { label: 'download(临时下载)', value: 'download' },
          ]}/>
        </Form.Item>
        <Form.Item name="duration_seconds" label="有效期(秒;留空 = 永久,仅 access 允许)">
          <InputNumber min={60} max={365 * 24 * 3600} style={{ width: '100%' }} placeholder="86400 = 24h" />
        </Form.Item>
        <Form.Item name="reason" label="理由" rules={[{ required: true, min: 4 }]}>
          <Input.TextArea rows={3} placeholder="给管理员看的说明" />
        </Form.Item>
      </Form>
    </Modal>
  );
}

export default function ApprovalsPage() {
  const [openNew, setOpenNew] = useState(false);
  return (
    <div>
      <AppBreadcrumb />
      <Tooltip title="新建申请 — 提交后管理员可在'待我审批'tab 批准或拒绝">
        <span />
      </Tooltip>
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
