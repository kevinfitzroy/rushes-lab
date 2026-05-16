/**
 * 分享 Modal — iter3 最小版。
 *
 * 简化:UserPicker 留到 D iter4 做(/users 接口未上);现在用 textarea 手输飞书 open_id,
 * 每行一个;支持"只发给我自己"快捷按钮。
 *
 * 提交成功后展示 landing_url(可复制)+ 每个 open_id 的推送结果(成功 / 失败)。
 */
import { App, Button, Form, Input, Modal, Select, Space, Tag, Typography } from 'antd';
import { CopyOutlined } from '@ant-design/icons';
import { useEffect, useState } from 'react';
import { useShareAsset, useShareFolder } from '../api/hooks';
import { errorMessage } from '../api/client';
import type { Me, ShareCreateOut } from '../api/types';

interface Props {
  open: boolean;
  onClose: () => void;
  target: { kind: 'asset' | 'folder'; id: string; label: string };
  me: Me;
}

const TTL_OPTIONS = [
  { label: '1 小时', value: 3600 },
  { label: '24 小时', value: 86400 },
  { label: '7 天', value: 7 * 86400 },
  { label: '30 天', value: 30 * 86400 },
];

export function ShareModal({ open, onClose, target, me }: Props) {
  const [form] = Form.useForm();
  const { message } = App.useApp();
  const shareAsset = useShareAsset();
  const shareFolder = useShareFolder();
  const [result, setResult] = useState<ShareCreateOut | null>(null);

  const loading = shareAsset.isPending || shareFolder.isPending;

  useEffect(() => {
    if (open) {
      form.resetFields();
      setResult(null);
    }
  }, [open, form]);

  const submit = async () => {
    try {
      const v = await form.validateFields();
      const open_ids = (v.open_ids as string || '')
        .split(/[\s,;]+/).map(s => s.trim()).filter(Boolean);
      const body = {
        receive_open_ids: open_ids,
        message: v.message?.trim() || undefined,
        expires_in_seconds: v.ttl as number,
        requires_login: true,
      };
      const data = target.kind === 'asset'
        ? await shareAsset.mutateAsync({ asset_id: target.id, ...body })
        : await shareFolder.mutateAsync({ folder_id: target.id, ...body });
      setResult(data);
      message.success(open_ids.length > 0 ? `分享链接已生成,推送 ${open_ids.length} 人` : '分享链接已生成');
    } catch (e) {
      if ((e as { errorFields?: unknown }).errorFields) return;
      message.error(errorMessage(e, '分享失败'));
    }
  };

  const copyLink = async (url: string) => {
    try {
      await navigator.clipboard.writeText(url);
      message.success('链接已复制');
    } catch {
      message.error('复制失败,请手动选择文本复制');
    }
  };

  return (
    <Modal
      title={`分享 ${target.kind === 'asset' ? '文件' : '文件夹'}`}
      open={open}
      onCancel={onClose}
      destroyOnClose
      footer={result ? (
        <Button onClick={onClose}>关闭</Button>
      ) : [
        <Button key="cancel" onClick={onClose}>取消</Button>,
        <Button key="ok" type="primary" loading={loading} onClick={submit}>
          生成分享 + 推送
        </Button>,
      ]}
    >
      {result ? (
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <div>
            <Typography.Text type="secondary">分享链接(有效期至 {new Date(result.expires_at).toLocaleString('zh-CN')})</Typography.Text>
            <Input.Group compact>
              <Input value={result.landing_url} readOnly style={{ width: 'calc(100% - 88px)' }} />
              <Button icon={<CopyOutlined />} onClick={() => copyLink(result.landing_url)}>复制</Button>
            </Input.Group>
          </div>
          {result.sent.length > 0 && (
            <div>
              <Typography.Text type="secondary">飞书 IM 推送结果</Typography.Text>
              <div style={{ marginTop: 8 }}>
                {result.sent.map((s, i) => (
                  <div key={i} style={{ marginBottom: 4, fontSize: 12 }}>
                    <code>{s.open_id.slice(0, 18)}…</code>{' '}
                    {s.error ? <Tag color="error">失败:{s.error.slice(0, 60)}</Tag>
                              : <Tag color="success">已送达</Tag>}
                  </div>
                ))}
              </div>
            </div>
          )}
        </Space>
      ) : (
        <Form form={form} layout="vertical" initialValues={{ ttl: 86400 }}>
          <Form.Item label="资源">
            <Typography.Text code>{target.label}</Typography.Text>
          </Form.Item>
          <Form.Item
            name="open_ids"
            label="飞书 open_id 列表"
            extra="每行一个,留空 = 只生成链接不推卡。临时简版,D 系列会出 UserPicker。"
          >
            <Input.TextArea rows={3} placeholder={`例:\nou_1566f9b88259da110781786c9fdd8804\n${me.open_id}`} />
          </Form.Item>
          <Form.Item>
            <Button size="small" onClick={() => form.setFieldValue('open_ids', me.open_id)}>
              只发给我自己 (测试用)
            </Button>
          </Form.Item>
          <Form.Item name="message" label="留言(可选)">
            <Input.TextArea rows={2} maxLength={500} showCount placeholder="可以留几句话" />
          </Form.Item>
          <Form.Item name="ttl" label="有效期" rules={[{ required: true }]}>
            <Select options={TTL_OPTIONS} />
          </Form.Item>
        </Form>
      )}
    </Modal>
  );
}
