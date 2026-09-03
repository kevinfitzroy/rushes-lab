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
          message="开发者通道(X-User-Id header 直连身份)"
          description="日常测试请走账号密码登录(/login,与生产同链路,local_up.sh 已为 seed 账号设好固定密码)。此页仅在 ENV=dev 生效:身份存 localStorage,后续请求自动附加 X-User-Id,适合临时冒烟任意 UUID。"
          style={{ marginBottom: 16 }}
        />
        <Button block style={{ marginBottom: 16 }} onClick={() => navigate('/login')}>
          前往账号密码登录 →
        </Button>

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
