/**
 * 全局 ErrorBoundary — 任何 render error 都展示友好错误页,而非白屏。
 */
import { Component, type ErrorInfo, type ReactNode } from 'react';
import { Button, Result, Typography } from 'antd';

interface Props { children: ReactNode }
interface State { error: Error | null }

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[ErrorBoundary]', error, info);
  }

  render() {
    if (this.state.error) {
      return (
        <Result
          status="error"
          title="页面出错了"
          subTitle={this.state.error.message}
          extra={[
            <Button key="reload" type="primary" onClick={() => location.reload()}>刷新页面</Button>,
            <Button key="home" onClick={() => { location.href = '/ms-static/web/'; }}>回首页</Button>,
          ]}
        >
          <Typography.Paragraph>
            <pre style={{ fontSize: 11, color: '#999', maxHeight: 200, overflow: 'auto' }}>
              {this.state.error.stack}
            </pre>
          </Typography.Paragraph>
        </Result>
      );
    }
    return this.props.children;
  }
}
