/**
 * 修改密码页(#149)。
 *
 * 两种进入方式:
 * - 强制流程:登录后 must_change_password=true,AppShell 路由守卫只放行本页
 * - 自愿流程:UserMenu「修改密码」(me.password_set 时可见)
 *
 * 未登录访问 → 跳 /login?next=/change-password。
 */
import { App, Alert, Button, Card, Form, Input, Typography } from 'antd';
import { Navigate, useNavigate } from 'react-router-dom';
import { errorMessage } from '../api/client';
import { useChangePassword, useMe } from '../api/hooks';

/** 镜像后端密码策略:≥8 位,且同时含字母和数字(AUTH_PASSWORD_MIN_LENGTH=8) */
const PW_RE = /^(?=.*[A-Za-z])(?=.*\d).{8,}$/;

export default function ChangePasswordPage() {
  const navigate = useNavigate();
  const { message } = App.useApp();
  const { data: me, isLoading, isError } = useMe();
  const change = useChangePassword();
  const [form] = Form.useForm();

  if (isLoading) return null; // AppShell 已展示加载态
  if (isError || !me) return <Navigate to="/login?next=/change-password" replace />;

  const forced = me.must_change_password;

  const onFinish = async (v: { old_password: string; new_password: string }) => {
    try {
      await change.mutateAsync({ old_password: v.old_password, new_password: v.new_password });
      message.success(forced ? '密码已设置' : '密码已修改');
      navigate('/', { replace: true });
    } catch (err) {
      message.error(errorMessage(err, '修改密码失败'));
    }
  };

  return (
    <div style={{ maxWidth: 520, margin: '64px auto', padding: 16 }}>
      <Card>
        <Typography.Title level={4} style={{ marginTop: 0, marginBottom: 4 }}>
          {forced ? '首次登录,请设置新密码' : '修改密码'}
        </Typography.Title>
        <Typography.Paragraph type="secondary" style={{ marginTop: 0 }}>
          {forced
            ? '为保护你的账号,首次登录必须设置新密码后才能继续使用。'
            : '请先验证原密码,再设置新密码。'}
        </Typography.Paragraph>

        {forced && (
          <Alert type="warning" style={{ marginBottom: 20 }}
                 message="密码重置" showIcon
                 description="新密码设置完成后将自动解除强制要求。" />
        )}

        <Form form={form} layout="vertical" onFinish={onFinish}>
          <Form.Item
            name="old_password"
            label="原密码"
            rules={[{ required: true, message: '请输入原密码' }]}
          >
            <Input.Password placeholder="原密码" autoFocus />
          </Form.Item>
          <Form.Item
            name="new_password"
            label="新密码"
            rules={[
              { required: true, message: '请输入新密码' },
              { pattern: PW_RE, message: '至少 8 位,且同时包含字母和数字' },
            ]}
          >
            <Input.Password placeholder="≥8 位,含字母和数字" />
          </Form.Item>
          <Form.Item
            name="confirm_password"
            label="确认新密码"
            dependencies={['new_password']}
            rules={[
              { required: true, message: '请再次输入新密码' },
              ({ getFieldValue }) => ({
                validator: (_rule, value) =>
                  !value || getFieldValue('new_password') === value
                    ? Promise.resolve()
                    : Promise.reject(new Error('两次输入的新密码不一致')),
              }),
            ]}
          >
            <Input.Password placeholder="再次输入新密码" />
          </Form.Item>
          <Form.Item style={{ marginBottom: 0 }}>
            <Button type="primary" htmlType="submit" block loading={change.isPending}>
              {forced ? '设置密码' : '确认修改'}
            </Button>
          </Form.Item>
        </Form>
      </Card>
    </div>
  );
}
