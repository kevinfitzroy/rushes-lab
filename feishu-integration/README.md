# feishu-integration

飞书(Feishu / Lark)集成层 —— 把"调用飞书开放平台"的能力封装成稳定 REST 接口,供仓库内其他项目调用。

## 角色

这是一个**桥接服务(bridge / middleware)**:

- **对内**(upstream:`material-storage` 等仓库内项目):暴露 REST API,语义化封装"申请审批 / 解析用户 / 推送消息 / SSO 鉴权"等业务能力
- **对外**(downstream:飞书开放平台):管理 `tenant_access_token`、接收事件 webhook、按飞书 API 协议调用

## 工作区边界

- **本目录(`feishu-integration/`)的所有代码与配置由 feishu agent 维护。** material-storage agent 不应在此目录提交。
- 与其他项目的对接走**契约**:`rushes-spec/feishu/contracts/*.md`,任何契约变更必须 PR review,双方都签字。
- 工作流细节、协作规则见 [`../rushes-spec/feishu/COLLABORATION.md`](../rushes-spec/feishu/COLLABORATION.md)。

## 状态

🟡 **连通性 PoC 已就位,等业务实施。** ADR-0001 + contract `approval.md` v1 已 merge(PR #4),实施分两步:

- **第一步(当前):连通性 PoC** —— 验证域名 / HTTPS / `tenant_access_token` / 事件回调握手通,代码在 [`app/main.py`](./app/main.py)
- **第二步:契约 v1 实施** —— `POST /approvals` / `GET /approvals/:id` / `POST /approvals/:id/withdraw` + bridge→upstream webhook,见 [`../rushes-spec/feishu/contracts/approval.md`](../rushes-spec/feishu/contracts/approval.md)

## 目录结构

```
feishu-integration/
├── app/
│   └── main.py                  ← PoC FastAPI app(healthz + lark callback + oauth 占位)
├── deploy/
│   ├── Caddyfile                ← 反代 + 自动 ACME
│   ├── feishu-poc.service       ← systemd unit
│   └── install_server.sh        ← 一次性服务器初始化脚本
├── .env.example                 ← env 变量名清单(变量名是契约,值不入仓库)
├── requirements.txt
└── README.md
```

## PoC 本地跑

```bash
cd feishu-integration
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # 填真值,不要 commit
set -a; . ./.env; set +a
uvicorn app.main:app --host 127.0.0.1 --port 8080 --reload
```

`curl http://127.0.0.1:8080/healthz` 应返回 `{"ok":true, "token_prefix":"t-xxxx", ...}`。

## PoC 部署到测试服(`rusheslab.taoxiplan.com` / `47.109.30.236`)

**前置:** `rusheslab.taoxiplan.com` A 记录已指 `47.109.30.236` 且全球可解析。

```bash
# 1. 把代码 rsync 到服务器
rsync -avz --exclude='.venv' --exclude='__pycache__' --exclude='.env' \
  feishu-integration/ root@47.109.30.236:/opt/feishu-poc/

# 2. 把本地 .env scp 上去(.env 不进 git)
scp feishu-integration/.env root@47.109.30.236:/opt/feishu-poc/.env

# 3. 远端跑一次安装脚本
ssh root@47.109.30.236 'bash /opt/feishu-poc/deploy/install_server.sh'

# 4. 验证
curl -sS https://rusheslab.taoxiplan.com/healthz
# → {"ok":true,"app_id":"cli_...","token_prefix":"t-xxx","token_expires_in":71xx}
```

## PoC 通过标准

1. ✅ `curl https://rusheslab.taoxiplan.com/healthz` 200 + `ok:true`(域名 + HTTPS + APP_ID/SECRET 都通)
2. ✅ 服务器 `journalctl -u feishu-poc -f` 启动日志能看到 `tenant_access_token refreshed: prefix=t-xxxx`
3. ✅ 飞书开发者后台 → 事件订阅 → "保存"事件回调地址,后台显示"验证通过"(说明 `ENCRYPT_KEY` + `VERIFICATION_TOKEN` 解码 + 校验都通)

## 技术栈(PoC 阶段)

- Python 3.10+ / FastAPI / uvicorn / httpx / cryptography
- 反代:Caddy(自动 Let's Encrypt)
- 部署:systemd(root,绑 127.0.0.1:8080,只通过 Caddy 暴露)
- **暂未引入**:`lark-oapi` SDK / Redis(契约 v1 实施阶段再加,PoC 用 stdlib + httpx 直调够用)

## 安全注意

- `.env` 包含 `FEISHU_APP_SECRET` / `FEISHU_ENCRYPT_KEY` / `FEISHU_VERIFICATION_TOKEN` 等敏感值,**永远不进 git**(`../.gitignore` 已覆盖)
- `.env.example` 只列变量名,不写真值
- bridge 暴露面是 Caddy 终结 HTTPS,FastAPI 自己绑 `127.0.0.1`,不直接对外
- OAuth 回调 `/login/callback` 当前只回 200,**不**做 code→token 换取(留给 MS-FB-004 契约阶段)
