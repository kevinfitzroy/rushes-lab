import { App, Button, Card, Form, Input, Space, Typography, Alert } from 'antd';
import { useNavigate } from 'react-router-dom';
import { getDevUserId, setDevUserId } from '../api/client';

const PRESETS = [
  { name: 'alice (admin)', id: '00000000-0000-0000-0000-000000000001' },
  { name: 'bob (member)', id: '00000000-0000-0000-0000-000000000002' },
];

export default function DevLoginPage() {
  const navigate = useNavigate();
  const { message } = App.useApp();
  const [form] = Form.useForm();

  const login = (id: string) => {
    setDevUserId(id);
    message.success(`dev login as ${id.slice(0, 8)}…`);
    setTimeout(() => navigate('/'), 200);
  };

  return (
    <div style={{ maxWidth: 520, margin: '64px auto', padding: 16 }}>
      <Card title="material-storage — dev login">
        <Alert
          type="info"
          message="开发模式 X-User-Id header 登录"
          description="生产部署应走飞书 OIDC(/api/v1/auth/login);此页用于 dev / smoke 测试。X-User-Id 存于 localStorage,后续所有 request 自动附加。"
          style={{ marginBottom: 16 }}
        />

        <Typography.Title level={5}>预设测试用户</Typography.Title>
        <Space direction="vertical" style={{ width: '100%' }}>
          {PRESETS.map(p => (
            <Button key={p.id} block onClick={() => login(p.id)}>
              {p.name} — <code>{p.id}</code>
            </Button>
          ))}
        </Space>

        <Typography.Title level={5} style={{ marginTop: 24 }}>自定义 UUID</Typography.Title>
        <Form form={form} layout="inline" initialValues={{ uuid: getDevUserId() ?? '' }}
              onFinish={(v) => login(v.uuid.trim())}>
          <Form.Item name="uuid" rules={[{ required: true, min: 36, max: 36 }]} style={{ flex: 1 }}>
            <Input placeholder="00000000-0000-0000-0000-000000000000" />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit">登录</Button>
          </Form.Item>
        </Form>

        <Button danger style={{ marginTop: 16 }} block
                onClick={() => { setDevUserId(null); message.info('已清除'); }}>
          清除 dev session
        </Button>
      </Card>
    </div>
  );
}
