/**
 * 短链落地页 — /s/{token}
 *
 * 行为:
 * - 调 GET /api/v1/share/{token}
 *   - 401 → axios interceptor 已跳 OIDC(回来后再次访问本页)
 *   - 200 + asset → 显示 + 自动触发下载
 *   - 200 + folder → 跳到 folder 详情页
 *   - 404 → 失效 / 不存在提示
 */
import { Alert, Button, Card, Descriptions, Result, Spin } from 'antd';
import { CloudDownloadOutlined, FolderOpenOutlined } from '@ant-design/icons';
import { useEffect, useRef } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useResolveShare } from '../api/hooks';

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}

export default function ShareLandingPage() {
  const { token } = useParams<{ token: string }>();
  const navigate = useNavigate();
  const { data, isLoading, isError, error } = useResolveShare(token);
  const downloadTriggered = useRef(false);

  // asset → 自动触发下载(只触发一次)
  useEffect(() => {
    if (data?.kind === 'asset' && data.download_url && !downloadTriggered.current) {
      downloadTriggered.current = true;
      // 用 <a> 触发下载,避免 window.location 改 URL
      const a = document.createElement('a');
      a.href = data.download_url;
      a.download = data.asset?.filename ?? '';
      a.style.display = 'none';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    }
  }, [data]);

  if (isLoading) {
    return <div style={{ padding: 80, textAlign: 'center' }}><Spin tip="解析分享链接…" size="large" /></div>;
  }

  if (isError) {
    const status = (error as { response?: { status?: number } })?.response?.status;
    if (status === 404) {
      return (
        <Result
          status="404"
          title="分享链接已失效"
          subTitle="链接可能已过期,或目标资源已被删除。可联系分享者重新生成。"
          extra={<Button type="primary" onClick={() => navigate('/')}>回到首页</Button>}
        />
      );
    }
    return (
      <Result
        status="error"
        title="加载失败"
        subTitle={String(error)}
        extra={<Button onClick={() => window.location.reload()}>重试</Button>}
      />
    );
  }

  if (!data) return null;

  if (data.kind === 'asset') {
    return (
      <div style={{ maxWidth: 640, margin: '40px auto' }}>
        <Card title="📨 分享文件">
          <Descriptions column={1} bordered size="small">
            <Descriptions.Item label="文件名">{data.asset?.filename}</Descriptions.Item>
            <Descriptions.Item label="大小">{data.asset && fmtBytes(data.asset.size_bytes)}</Descriptions.Item>
            <Descriptions.Item label="类型">{data.asset?.content_type ?? '—'}</Descriptions.Item>
            <Descriptions.Item label="分享者">{data.sharer_name ?? '(未知)'}</Descriptions.Item>
            <Descriptions.Item label="链接有效期至">{new Date(data.expires_at).toLocaleString('zh-CN')}</Descriptions.Item>
          </Descriptions>
          <Alert
            style={{ marginTop: 16 }}
            type="info"
            showIcon
            message="下载应该已自动开始。未触发请点击下方按钮。"
          />
          <Button
            type="primary"
            icon={<CloudDownloadOutlined />}
            size="large"
            block
            style={{ marginTop: 16 }}
            href={data.download_url}
            download={data.asset?.filename}
          >
            手动下载
          </Button>
        </Card>
      </div>
    );
  }

  // folder
  return (
    <div style={{ maxWidth: 640, margin: '40px auto' }}>
      <Card title="📁 分享文件夹">
        <Descriptions column={1} bordered size="small">
          <Descriptions.Item label="名称">{data.folder?.name}</Descriptions.Item>
          <Descriptions.Item label="敏感">{data.folder?.is_sensitive ? '是' : '否'}</Descriptions.Item>
          <Descriptions.Item label="分享者">{data.sharer_name ?? '(未知)'}</Descriptions.Item>
          <Descriptions.Item label="链接有效期至">{new Date(data.expires_at).toLocaleString('zh-CN')}</Descriptions.Item>
        </Descriptions>
        <Button
          type="primary"
          icon={<FolderOpenOutlined />}
          size="large"
          block
          style={{ marginTop: 16 }}
          onClick={() => navigate(`/projects/${data.folder!.project_id}/folders/${data.folder!.id}`)}
        >
          打开文件夹
        </Button>
      </Card>
    </div>
  );
}
