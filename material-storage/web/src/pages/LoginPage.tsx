/**
 * 本地账号密码登录页(#149;#154:飞书 OIDC 入口下线,ADR-0007)。
 *
 * 未登录用户统一被 AppShell / client.ts 401 拦截器带 `?next=` 引导到这里;
 * 登录成功回 next(首登强制改密 → /change-password)。
 */
import { App, Alert, Button, Card, Form, Input, Typography } from 'antd';
import { KeyRound, User as UserIcon } from 'lucide-react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { errorMessage } from '../api/client';
import { useLocalLogin } from '../api/hooks';

const BASENAME = '/ms-static/web';

/** next 参数(window.location 级完整路径)→ react-router basename 相对路径。 */
function parseNext(raw: string | null): string {
  let n = (raw || '').split('#')[0].split('?')[0];
  if (n.startsWith(BASENAME)) n = n.slice(BASENAME.length);
  if (!n.startsWith('/')) n = '/';
  return n || '/';
}

export default function LoginPage() {
  const navigate = useNavigate();
  const { message } = App.useApp();
  const [params] = useSearchParams();
  const login = useLocalLogin();
  const [form] = Form.useForm();
  const next = parseNext(params.get('next'));

  const onFinish = async (values: { username: string; password: string }) => {
    try {
      const res = await login.mutateAsync(values);
      message.success(`欢迎,${res.name || '已登录'}`);
      if (res.must_change_password) {
        navigate('/change-password', { replace: true });
      } else {
        navigate(next, { replace: true });
      }
    } catch (err) {
      message.error(errorMessage(err, '登录失败'));
    }
  };

  return (
    <div style={{ maxWidth: 520, margin: '64px auto', padding: 16 }}>
      <Card>
        {/* 品牌印记(与 AppHeader 一致的几何方块) */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
          <span style={{ position: 'relative', display: 'inline-block', width: 22, height: 22 }}>
            <span style={{
              position: 'absolute', left: 0, top: 0,
              width: 14, height: 14, background: 'var(--ms-ink)', borderRadius: 2,
            }} />
            <span style={{
              position: 'absolute', left: 4, top: 4,
              width: 14, height: 14, background: 'var(--ms-accent)', borderRadius: 2, opacity: 0.85,
            }} />
            <span style={{
              position: 'absolute', left: 8, top: 8,
              width: 14, height: 14, background: 'var(--ms-emerald)', borderRadius: 2, opacity: 0.7,
            }} />
          </span>
          <span style={{
            fontFamily: 'var(--ms-font-display)', fontWeight: 500, fontSize: 16,
            letterSpacing: '-0.01em', color: 'var(--ms-ink)',
          }}>
            material<span style={{ color: 'var(--ms-accent)' }}>·</span>storage
          </span>
        </div>

        <Typography.Title level={4} style={{ marginTop: 8, marginBottom: 4 }}>
          账号密码登录
        </Typography.Title>
        <Typography.Paragraph type="secondary" style={{ marginTop: 0 }}>
          使用本地账号登录(工号 / 拼音用户名 / 邮箱均可)
        </Typography.Paragraph>

        <Alert
          type="info"
          style={{ marginBottom: 20 }}
          message="首次登录需设置新密码"
          description="初始密码由管理员分配;首次登录成功后系统会要求你设置自己的新密码。"
        />

        <Form form={form} layout="vertical" onFinish={onFinish}
              initialValues={{ username: '', password: '' }}>
          <Form.Item
            name="username"
            label="用户名"
            rules={[{ required: true, message: '请输入用户名' }]}
          >
            <Input prefix={<UserIcon size={14} />} placeholder="工号 / 拼音用户名 / 邮箱" autoFocus />
          </Form.Item>
          <Form.Item
            name="password"
            label="密码"
            rules={[{ required: true, message: '请输入密码' }]}
          >
            <Input.Password prefix={<KeyRound size={14} />} placeholder="密码" />
          </Form.Item>
          <Form.Item style={{ marginBottom: 8 }}>
            <Button type="primary" htmlType="submit" block loading={login.isPending}>
              登录
            </Button>
          </Form.Item>
        </Form>
      </Card>
      <div style={{ textAlign: 'center', marginTop: 16, fontSize: 12, color: 'var(--ms-ink-subtle)' }}>
        连续 5 次登录失败将锁定 15 分钟
      </div>
    </div>
  );
}
