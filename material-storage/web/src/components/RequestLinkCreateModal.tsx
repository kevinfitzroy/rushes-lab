import { App, Button, Form, Input, Modal, Segmented, Select } from 'antd';
import { Copy, Check } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useCreateRequestLink, type RequestLinkCreateOut } from '../api/hooks';
import { errorMessage } from '../api/client';

interface Props {
  open: boolean;
  onClose: () => void;
  targetType: 'sensitive_folder' | 'asset' | 'project';
  targetId: string;
  targetName: string;
}

const TTL_PRESETS = [
  { label: '1 小时', value: 3600 },
  { label: '1 天', value: 86400 },
  { label: '3 天', value: 3 * 86400 },
  { label: '7 天', value: 7 * 86400 },
] as const;

/**
 * #112 PR-2 — admin 生成 request link modal。
 * Step1 选 actions / TTL / 可选 receiver,提交后 step2 显 token + copy 按钮。
 */
export function RequestLinkCreateModal({ open, onClose, targetType, targetId, targetName }: Props) {
  const { message } = App.useApp();
  const create = useCreateRequestLink();
  const [form] = Form.useForm();
  const [result, setResult] = useState<RequestLinkCreateOut | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (open) {
      setResult(null);
      setCopied(false);
      form.resetFields();
    }
  }, [open, form]);

  // sensitive_folder 才能 access,其他只能 download
  const canAccess = targetType === 'sensitive_folder';
  const defaultActions = canAccess ? ['access', 'download'] : ['download'];

  const submit = async () => {
    try {
      const v = await form.validateFields();
      const out = await create.mutateAsync({
        target_type: targetType,
        target_id: targetId,
        allowed_actions: v.allowed_actions,
        receiver_open_id: v.receiver_open_id?.trim() || undefined,
        ttl_seconds: v.ttl_seconds,
      });
      setResult(out);
    } catch (e) {
      if ((e as { errorFields?: unknown }).errorFields) return;
      message.error(errorMessage(e, '生成失败'));
    }
  };

  const copy = async () => {
    if (!result) return;
    try {
      await navigator.clipboard.writeText(result.landing_url);
      setCopied(true);
      message.success('链接已复制');
      setTimeout(() => setCopied(false), 2000);
    } catch {
      message.error('复制失败,请手动选中链接');
    }
  };

  return (
    <Modal
      title={result ? '链接已生成' : `生成申请链接 — ${targetName}`}
      open={open}
      onCancel={onClose}
      destroyOnClose
      footer={result ? (
        <Button type="primary" onClick={onClose}>完成</Button>
      ) : (
        <>
          <Button onClick={onClose}>取消</Button>
          <Button type="primary" loading={create.isPending} onClick={submit}>
            生成
          </Button>
        </>
      )}
    >
      {!result && (
        <>
          <div style={{
            marginBottom: 12, fontSize: 12.5, color: 'var(--ms-ink-muted)',
            lineHeight: 1.6,
          }}>
            生成后把链接发给接收者,他点开后能看到资源信息并发起申请,
            <strong>不直接获得权限</strong>。你照常 IM 卡片审批后才生效。
          </div>
          <Form form={form} layout="vertical"
                initialValues={{
                  allowed_actions: defaultActions,
                  ttl_seconds: 3 * 86400,
                }}>
            <Form.Item name="allowed_actions" label="允许接收者申请的动作"
                       rules={[{ required: true, message: '至少选一个动作' }]}>
              <Select
                mode="multiple"
                options={[
                  ...(canAccess ? [{ value: 'access', label: '访问(进入敏感目录)' }] : []),
                  { value: 'download', label: '下载' },
                ]}
                placeholder="可多选"
              />
            </Form.Item>
            <Form.Item name="ttl_seconds" label="链接有效期" rules={[{ required: true }]}>
              <Segmented
                options={TTL_PRESETS.map(p => ({ label: p.label, value: p.value }))}
              />
            </Form.Item>
            <Form.Item name="receiver_open_id"
                       label="限定接收者 open_id(可选)"
                       extra="留空 = 任意登录用户可用;填了 = 只此 open_id 能用(防转发)">
              <Input placeholder="ou_xxxxxxxxx(可选)" />
            </Form.Item>
          </Form>
        </>
      )}

      {result && (
        <div>
          <div style={{
            marginBottom: 12, fontSize: 12.5, color: 'var(--ms-ink-muted)',
            lineHeight: 1.6,
          }}>
            把下面的链接发给接收者(IM / 邮件 / 复制粘贴均可)。链接将在 <strong>
              {new Date(result.expires_at).toLocaleString()}
            </strong> 过期。
          </div>
          <div style={{
            display: 'flex', alignItems: 'center', gap: 8,
            padding: '10px 12px',
            background: 'var(--ms-hairline-soft)',
            border: '1px solid var(--ms-hairline)',
            borderRadius: 'var(--ms-radius-md)',
          }}>
            <code style={{
              flex: 1, minWidth: 0,
              fontFamily: 'var(--ms-font-mono)', fontSize: 12,
              color: 'var(--ms-ink)',
              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            }}>{result.landing_url}</code>
            <Button
              size="small"
              icon={copied ? <Check size={13} strokeWidth={2.2} /> : <Copy size={13} strokeWidth={2.2} />}
              onClick={copy}
            >{copied ? '已复制' : '复制'}</Button>
          </div>
          <div style={{
            marginTop: 10, fontSize: 11.5, color: 'var(--ms-ink-subtle)',
          }}>
            允许动作:{result.allowed_actions.join(' / ')}
          </div>
        </div>
      )}
    </Modal>
  );
}
