import { App, Form, Input, InputNumber, Modal, Radio } from 'antd';
import { useEffect } from 'react';
import { useCreateApproval } from '../api/hooks';
import { errorMessage } from '../api/client';

interface Props {
  open: boolean;
  onClose: () => void;
  targetId: string;
  targetName: string;
  targetType: 'sensitive_folder' | 'asset' | 'project';
  defaultAction?: 'access' | 'download';
}

export function RequestAccessModal({ open, onClose, targetId, targetName, targetType, defaultAction = 'access' }: Props) {
  const create = useCreateApproval();
  const [form] = Form.useForm();
  const { message } = App.useApp();

  useEffect(() => {
    if (open) form.resetFields();
  }, [open, form]);

  return (
    <Modal
      title={`申请 — ${targetName}`}
      open={open}
      onCancel={onClose}
      destroyOnClose
      onOk={async () => {
        try {
          const v = await form.validateFields();
          await create.mutateAsync({
            target_type: targetType,
            target_id: targetId,
            action: v.action,
            duration_seconds: v.duration_seconds || undefined,
            reason: v.reason,
          });
          message.success('申请已提交');
          onClose();
        } catch (e) {
          if ((e as { errorFields?: unknown }).errorFields) return; // form validation
          message.error(errorMessage(e, '提交失败'));
        }
      }}
      confirmLoading={create.isPending}
    >
      <Form form={form} layout="vertical"
            initialValues={{ action: defaultAction, duration_seconds: defaultAction === 'access' ? undefined : 3600 }}>
        <Form.Item name="action" label="操作类型" rules={[{ required: true }]}>
          <Radio.Group>
            <Radio value="access" disabled={targetType !== 'sensitive_folder'}>访问(进入敏感目录)</Radio>
            <Radio value="download">下载({targetType === 'asset' ? '单文件' : '批量'})</Radio>
          </Radio.Group>
        </Form.Item>
        <Form.Item shouldUpdate={(p, c) => p.action !== c.action} noStyle>
          {({ getFieldValue }) => getFieldValue('action') === 'download' && (
            <Form.Item name="duration_seconds" label="有效期(秒)"
                       extra="留空 = 永久(仅 access 时允许)" rules={[{ required: true, min: 60 }]}>
              <InputNumber min={60} max={365 * 24 * 3600} style={{ width: '100%' }}
                           placeholder="86400 = 24h;604800 = 7d" />
            </Form.Item>
          )}
        </Form.Item>
        <Form.Item name="reason" label="申请理由"
                   rules={[{ required: true, min: 4, message: '理由至少 4 个字' }]}>
          <Input.TextArea rows={4} placeholder="说明为什么需要这个权限,管理员会看到" />
        </Form.Item>
      </Form>
    </Modal>
  );
}
