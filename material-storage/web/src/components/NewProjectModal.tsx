/**
 * 新建项目 — 仅系统 admin 可用;创建时必须指派项目 admin(默认 = 自己,可改)。
 */
import { Alert, App, Form, Input, Modal, Select } from 'antd';
import { ShieldCheck } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useCreateProject } from '../api/hooks';
import { errorMessage } from '../api/client';
import type { Me } from '../api/types';
import { UserPicker } from './UserPicker';

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
  const [adminOpenId, setAdminOpenId] = useState<string>(me.open_id);

  useEffect(() => {
    if (open) {
      form.resetFields();
      setAdminOpenId(me.open_id);  // 默认 admin = 自己
    }
  }, [open, form, me.open_id]);

  const submit = async () => {
    try {
      const v = await form.validateFields();
      if (!adminOpenId) {
        message.warning('请指派项目管理员');
        return;
      }
      const p = await create.mutateAsync({
        code: v.code.trim(),
        name: v.name.trim(),
        description: v.description?.trim() || undefined,
        organization_id: '',
        minio_bucket: v.minio_bucket || 'ms-dev',
        admin_user_open_id: adminOpenId,
      });
      message.success(`项目 "${p.name}" 已创建`);
      onCreated?.(p.id);
      onClose();
    } catch (e) {
      if ((e as { errorFields?: unknown }).errorFields) return;
      message.error(errorMessage(e, '创建失败'));
    }
  };

  // 非系统 admin → 禁用并提示
  if (!me.is_system_admin) {
    return (
      <Modal title="新建项目" open={open} onCancel={onClose} footer={null}>
        <Alert
          type="warning"
          showIcon
          message="只有系统管理员可以创建项目"
          description="如需新建项目,请联系系统管理员;管理员通过后台命令 grant_org_admin 指定。"
          style={{ marginTop: 4 }}
        />
      </Modal>
    );
  }

  return (
    <Modal
      title="新建项目"
      open={open}
      onCancel={onClose}
      destroyOnClose
      confirmLoading={create.isPending}
      onOk={submit}
      okText="创建"
    >
      <Form form={form} layout="vertical"
            initialValues={{ minio_bucket: 'ms-dev' }}>
        <Form.Item name="name" label="项目名称"
                   rules={[{ required: true, max: 255 }]}>
          <Input placeholder="2026 春季婚礼策划" autoFocus />
        </Form.Item>
        <Form.Item name="code" label="项目编码(URL slug,小写字母/数字/-)"
                   rules={[{
                     required: true, min: 2, max: 64,
                     pattern: /^[a-z0-9][a-z0-9-]*$/,
                     message: '小写字母/数字/-,以字母数字开头',
                   }]}
                   extra="提交后不可改;影响 MinIO 路径前缀">
          <Input placeholder="wedding-2026-spring" />
        </Form.Item>
        <Form.Item name="description" label="描述(可选)">
          <Input.TextArea rows={3} maxLength={500} showCount />
        </Form.Item>

        {/* 指派 admin — 系统 admin 必填,默认自己 */}
        <Form.Item label="项目管理员"
                   extra="可以是自己;创建后会自动获得项目内全部权限,并可进一步邀请成员">
          <UserPicker
            multiple={false}
            value={adminOpenId}
            onChange={(v) => setAdminOpenId((v as string) || '')}
            preset={[{ id: me.id, open_id: me.open_id, union_id: me.union_id,
                       name: me.name + '(自己)', email: me.email }]}
            placeholder="选一个项目管理员"
          />
          {adminOpenId === me.open_id && (
            <div style={{
              marginTop: 6, fontSize: 11, color: 'var(--ms-ink-subtle)',
              display: 'inline-flex', alignItems: 'center', gap: 4,
            }}>
              <ShieldCheck size={11} strokeWidth={1.8} />
              你本人将作为项目管理员
            </div>
          )}
        </Form.Item>

        <Form.Item name="minio_bucket" label="MinIO bucket"
                   rules={[{ required: true, max: 63 }]}
                   extra="PoC 统一 ms-dev">
          <Select options={[
            { label: 'ms-dev(开发环境)', value: 'ms-dev' },
          ]} />
        </Form.Item>
      </Form>
    </Modal>
  );
}
