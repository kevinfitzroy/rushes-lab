import { App, Form, Input, Modal, Switch, Typography } from 'antd';
import { useEffect } from 'react';
import { useCreateFolder } from '../api/hooks';
import { errorMessage } from '../api/client';

interface Props {
  open: boolean;
  onClose: () => void;
  projectId: string;
  parentFolderId?: string;
  parentName?: string;          // 显示用 — '当前位于 raw/特写/新人'
  parentIsSensitive?: boolean;  // 父 sensitive 时新 folder 强制 sensitive(继承)
  onCreated?: (folder_id: string) => void;
}

export function NewFolderModal({
  open, onClose, projectId, parentFolderId, parentName, parentIsSensitive, onCreated,
}: Props) {
  const create = useCreateFolder();
  const [form] = Form.useForm();
  const { message } = App.useApp();

  useEffect(() => {
    if (open) form.resetFields();
  }, [open, form]);

  return (
    <Modal
      title="新建文件夹"
      open={open}
      onCancel={onClose}
      destroyOnClose
      confirmLoading={create.isPending}
      onOk={async () => {
        try {
          const v = await form.validateFields();
          const f = await create.mutateAsync({
            project_id: projectId,
            parent_folder_id: parentFolderId,
            name: v.name.trim(),
            is_sensitive: parentIsSensitive || v.is_sensitive || false,
          });
          message.success(`文件夹 "${f.name}" 已创建`);
          onCreated?.(f.id);
          onClose();
        } catch (e) {
          if ((e as { errorFields?: unknown }).errorFields) return;
          message.error(errorMessage(e, '创建失败'));
        }
      }}
    >
      <Form form={form} layout="vertical" initialValues={{ is_sensitive: false }}>
        <Form.Item label="位置">
          <Typography.Text type="secondary" code style={{ fontSize: 12 }}>
            {parentName ? `项目根 / ${parentName}` : '项目根'}
          </Typography.Text>
        </Form.Item>
        <Form.Item name="name" label="文件夹名"
                   rules={[{ required: true, min: 1, max: 255 }]}>
          <Input placeholder="例:现场原片 / 第 3 次 / 精修" autoFocus />
        </Form.Item>
        {parentIsSensitive ? (
          <Typography.Text type="warning" style={{ fontSize: 12 }}>
            父 folder 已为 sensitive,新建子 folder 自动继承 sensitive
          </Typography.Text>
        ) : (
          <Form.Item name="is_sensitive" label="标为 sensitive"
                     extra="sensitive folder 默认所有 project member 看不到,仅 admin 邀请的可见"
                     valuePropName="checked">
            <Switch />
          </Form.Item>
        )}
      </Form>
    </Modal>
  );
}
