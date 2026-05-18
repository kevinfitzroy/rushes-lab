import { App, Form, Input, InputNumber, Modal, Radio, Segmented, Select } from 'antd';
import { useEffect, useState } from 'react';
import { useCreateApproval } from '../api/hooks';
import { errorMessage } from '../api/client';

interface Props {
  open: boolean;
  onClose: () => void;
  targetId: string;
  targetName: string;
  targetType: 'sensitive_folder' | 'asset' | 'project';
  defaultAction?: 'access' | 'download';
  // #112 PR-2: 由 request-link 落地页注入约束动作集;不传 = 不约束(原行为)
  allowedActions?: ('access' | 'download')[];
  // 同时 POST 时附带 via_link query param 给 backend enforce
  viaLink?: string;
}

// #119 修:有效期改预设按钮 + 自定义(原来要求用户填裸秒数,unfriendly)
const DURATION_PRESETS = [
  { label: '15 分钟', seconds: 15 * 60 },
  { label: '1 小时', seconds: 3600 },
  { label: '1 天', seconds: 86400 },
  { label: '7 天', seconds: 7 * 86400 },
  { label: '30 天', seconds: 30 * 86400 },
] as const;

/** 受控 — 通过 Form.Item 注入 value/onChange,写 form 的 duration_seconds(number) */
function DurationControl({ value, onChange }: { value?: number; onChange?: (v: number) => void }) {
  const presetSeconds = DURATION_PRESETS.map(p => p.seconds);
  const isCustom = value != null && !presetSeconds.includes(value as typeof presetSeconds[number]);
  const [customValue, setCustomValue] = useState<number>(
    isCustom ? Math.max(1, Math.round((value ?? 3600) / 3600)) : 1
  );
  const [customUnit, setCustomUnit] = useState<60 | 3600 | 86400>(
    isCustom && value && value % 86400 === 0 ? 86400
    : isCustom && value && value % 3600 === 0 ? 3600
    : isCustom ? 60 : 3600
  );

  const segValue = isCustom ? 'custom' : (value ?? 3600);

  return (
    <>
      <Segmented
        value={segValue as string | number}
        onChange={(val) => {
          if (val === 'custom') {
            onChange?.(customValue * customUnit);
          } else {
            onChange?.(val as number);
          }
        }}
        options={[
          ...DURATION_PRESETS.map(p => ({ label: p.label, value: p.seconds })),
          { label: '自定义', value: 'custom' },
        ]}
      />
      {isCustom && (
        <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
          <InputNumber
            min={1} max={365}
            value={customValue}
            onChange={(n) => {
              const next = n ?? 1;
              setCustomValue(next);
              onChange?.(next * customUnit);
            }}
            style={{ flex: 1 }}
            placeholder="数值"
          />
          <Select
            value={customUnit}
            onChange={(u) => {
              setCustomUnit(u);
              onChange?.(customValue * u);
            }}
            options={[
              { label: '分钟', value: 60 },
              { label: '小时', value: 3600 },
              { label: '天', value: 86400 },
            ]}
            style={{ width: 90 }}
          />
        </div>
      )}
    </>
  );
}

export function RequestAccessModal({
  open, onClose, targetId, targetName, targetType,
  defaultAction = 'access', allowedActions, viaLink,
}: Props) {
  const create = useCreateApproval();
  const [form] = Form.useForm();
  const { message } = App.useApp();

  // 若 allowedActions 注入且 default 不在允许集,fallback 到第一个允许的
  const effectiveDefault: 'access' | 'download' =
    allowedActions && allowedActions.length > 0 && !allowedActions.includes(defaultAction)
      ? allowedActions[0]
      : defaultAction;

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
            via_link: viaLink,
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
            initialValues={{ action: effectiveDefault, duration_seconds: effectiveDefault === 'access' ? undefined : 3600 }}>
        <Form.Item name="action" label="操作类型" rules={[{ required: true }]}>
          <Radio.Group>
            <Radio value="access"
                   disabled={targetType !== 'sensitive_folder'
                             || (!!allowedActions && !allowedActions.includes('access'))}>
              访问(进入敏感目录)
            </Radio>
            <Radio value="download"
                   disabled={!!allowedActions && !allowedActions.includes('download')}>
              下载({targetType === 'asset' ? '单文件' : '批量'})
            </Radio>
          </Radio.Group>
        </Form.Item>
        <Form.Item shouldUpdate={(p, c) => p.action !== c.action} noStyle>
          {({ getFieldValue }) => getFieldValue('action') === 'download' && (
            <Form.Item name="duration_seconds" label="有效期"
                       rules={[{ required: true, type: 'number', min: 60, message: '请选择或输入至少 1 分钟' }]}>
              <DurationControl />
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
