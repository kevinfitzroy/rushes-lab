import { App, Form, Input, Modal, Select } from 'antd';
import { useEffect } from 'react';
import { useCreateProject } from '../api/hooks';
import { errorMessage } from '../api/client';
import type { Me } from '../api/types';

interface Props {
  open: boolean;
  onClose: () => void;
  onCreated?: (project_id: string) => void;
  me: Me;
}

export function NewProjectModal({ open, onClose, onCreated, me }: Props) {
  const create = useCreateProject();
  const [form] = Form.useForm();
  const { message } = App.useApp();

  useEffect(() => {
    if (open) form.resetFields();
  }, [open, form]);

  return (
    <Modal
      title="新建项目"
      open={open}
      onCancel={onClose}
      destroyOnClose
      confirmLoading={create.isPending}
      onOk={async () => {
        try {
          const v = await form.validateFields();
          const p = await create.mutateAsync({
            code: v.code.trim(),
            name: v.name.trim(),
            description: v.description?.trim() || undefined,
            organization_id: v.organization_id,
            minio_bucket: v.minio_bucket || 'ms-dev',
          });
          message.success(`项目 "${p.name}" 已创建`);
          onCreated?.(p.id);
          onClose();
        } catch (e) {
          if ((e as { errorFields?: unknown }).errorFields) return;
          message.error(errorMessage(e, '创建失败'));
        }
      }}
    >
      <Form form={form} layout="vertical"
            initialValues={{
              organization_id: me.organization_id ?? '',
              minio_bucket: 'ms-dev',
              visibility: 'private',
            }}>
        <Form.Item name="name" label="项目名称"
                   rules={[{ required: true, max: 255 }]}>
          <Input placeholder="2026 春季婚礼策划" />
        </Form.Item>
        <Form.Item name="code" label="项目编码(URL slug,小写字母/数字/-)"
                   rules={[{
                     required: true, min: 2, max: 64,
                     pattern: /^[a-z0-9][a-z0-9-]*$/,
                     message: '小写字母/数字/-,以字母数字开头',
                   }]}>
          <Input placeholder="wedding-2026-spring" />
        </Form.Item>
        <Form.Item name="description" label="描述">
          <Input.TextArea rows={3} maxLength={500} showCount placeholder="可选" />
        </Form.Item>
        <Form.Item name="organization_id" label="组织 ID(默认你所在组织)"
                   rules={[{ required: true }]}>
          <Input disabled={!!me.organization_id} />
        </Form.Item>
        <Form.Item name="minio_bucket" label="MinIO bucket"
                   rules={[{ required: true, max: 63 }]}
                   extra="存储桶名;PoC 统一用 ms-dev">
          <Select options={[
            { label: 'ms-dev(开发环境)', value: 'ms-dev' },
          ]} />
        </Form.Item>
      </Form>
    </Modal>
  );
}
