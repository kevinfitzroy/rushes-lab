# material-storage API

业务后端。架构与选型见 [ADR-0005](../../rushes-spec/material-storage/decisions/0005-drop-seafile-middle-layer-minio-only.md) + [ADR-0006](../../rushes-spec/material-storage/decisions/0006-phase-b-tech-stack.md)。

## 当前状态

**Phase B 主体已实施 + 部署 server2 dev**(`http://8.156.34.238/`)。迭代细节、待办、已知坑见 [`../../rushes-spec/material-storage/ROADMAP.md`](../../rushes-spec/material-storage/ROADMAP.md)。

## 技术栈(ADR-0006)

- Python 3.12 + FastAPI + Pydantic v2
- PostgreSQL 16(SQLAlchemy 2.x async + alembic)
- Redis 7(arq queue + cache)
- MinIO via boto3 / aioboto3
- OpenFGA(ReBAC 权限)via openfga-sdk
- 本地账号密码登录 + 可选 OIDC provider(#154:飞书下线,ADR-0007)
- 包管理 uv;lint ruff;type mypy;test pytest async

## 项目结构

```
api/
├── app/
│   ├── main.py             FastAPI app + lifespan + router wiring + StaticFiles for /static/web
│   ├── settings.py         Pydantic Settings(env-driven)
│   ├── deps.py             DI:db / openfga / s3 / get_current_user / get_is_system_admin
│   ├── routers/            REST endpoints(按业务域分包)
│   │   ├── auth.py           本地登录 + 可选 OIDC provider login / callback / session
│   │   ├── projects.py       project CRUD + 成员管理
│   │   ├── folders.py        folder 树 / sensitive 申请
│   │   ├── assets.py         asset 上传(presigned)/ 下载 / 列表
│   │   ├── approvals.py      sensitive folder 审批
│   │   ├── share.py          分享链接生成 / 落地
│   │   ├── admin.py          系统 admin 管理 + audit 查询
│   │   └── users.py          本地用户 / 组管理(#150)
│   ├── services/           业务逻辑
│   │   ├── permissions.py    openfga-sdk wrapper(grant / check / list_objects / is_org_admin)
│   │   ├── presign.py        boto3 presigned URL
│   │   ├── audit.py          audit-schema 落库
│   │   └── ...
│   ├── db/
│   │   ├── tables.py         SQLAlchemy 2.x models
│   │   └── migrations/       alembic
│   ├── models/             Pydantic schemas(API I/O)
│   ├── workers/main.py     arq tasks(缩略图等)
│   └── static/web/         前端 build 产物(StaticFiles mount,/static/web → ./app/static/web)
├── scripts/
│   ├── deploy_server2.sh     rsync + ssh 部署到 server2
│   ├── seed_admin_projects.py 批量建项目(每人 1 个 admin 项目)
│   ├── grant_org_admin.py    系统 admin 增删改查
│   └── ...
├── tests/
├── pyproject.toml          uv 包管理
├── alembic.ini
├── Dockerfile              uvicorn --proxy-headers --forwarded-allow-ips '*'
├── docker-compose.yml      ms-api + ms-db + ms-redis + ms-worker(+ poc-* services 外部)
├── .env.example
└── README.md
```

## 本地启动

### Prereq
- 起 dep 服务:`../poc/minio/docker-compose up -d`(MinIO + OpenFGA + nginx)
- 安装 [uv](https://github.com/astral-sh/uv)
- OIDC provider 凭据(可选,默认纯本地登录;本地 dev 通常走 `X-User-Id` header dev 模式)

### 启动
```bash
cp .env.example .env       # 编辑填 OPENFGA_URL / DB_URL / S3_* / SESSION_JWT_SECRET 等
uv sync                    # 装依赖
uv run uvicorn app.main:app --reload    # 启动 :8000
curl http://localhost:8000/api/v1/healthz

# 测试
uv run pytest -v

# lint / type
uv run ruff check .
uv run mypy app
```

### docker-compose
```bash
docker compose up -d
docker compose logs -f ms-api
```

## 部署到 server2 dev

```bash
# 详见 ../../rushes-spec/material-storage/ops-manual.md §2 + scripts/deploy_server2.sh
./scripts/deploy_server2.sh           # rsync app + dist;默认保留远端 .env
INIT_ENV=1 ./scripts/deploy_server2.sh  # 覆盖远端 .env(谨慎!)

# 远端 reload(.py 是 bind mount,改代码后)
ssh root@8.156.34.238 'cd /opt/material-storage && docker compose restart ms-api'

# 改 .env 后必须 force-recreate
ssh root@8.156.34.238 'cd /opt/material-storage && docker compose up -d --force-recreate ms-api'
```

`ops-manual.md` 有完整 cheat sheet 包括 admin 管理、审计排查等。

## 关键文档

| | 看 |
| --- | --- |
| 当前迭代 / 已知坑 | [`../../rushes-spec/material-storage/ROADMAP.md`](../../rushes-spec/material-storage/ROADMAP.md) |
| 运维 / 部署 / 排查 | [`../../rushes-spec/material-storage/ops-manual.md`](../../rushes-spec/material-storage/ops-manual.md) |
| 权限模型 v4(改 permission 代码前必读) | [`../../rushes-spec/material-storage/permissions-model-v4.md`](../../rushes-spec/material-storage/permissions-model-v4.md) |
| OpenFGA model | [`../poc/openfga/store.fga.yaml`](../poc/openfga/store.fga.yaml) |
| 测试反馈协作 | [`../../rushes-spec/material-storage/COLLABORATION.md`](../../rushes-spec/material-storage/COLLABORATION.md) |
