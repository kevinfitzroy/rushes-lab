# material-storage API — Phase B-1 skeleton

> 业务后端 implementation。架构与选型见 [ADR-0005](../../rushes-spec/material-storage/decisions/0005-drop-seafile-middle-layer-minio-only.md) + [ADR-0006](../../rushes-spec/material-storage/decisions/0006-phase-b-tech-stack.md)。

## 当前状态:**Phase B-1 skeleton(2026-05-16)**

只有项目结构 + healthz endpoint + router stub + 测试骨架,**无业务逻辑**。Phase B-2 起填实际 endpoint。

## 技术栈(ADR-0006)

- Python 3.12 + FastAPI + Pydantic v2
- PostgreSQL 16(SQLAlchemy 2.x async + alembic)
- Redis 7(arq queue + cache)
- MinIO via boto3 / aioboto3
- OpenFGA(权限)via openfga-sdk
- 飞书 SDK lark-oapi(`larksuite/oapi-sdk-python`)
- 包管理 uv;lint ruff;type mypy strict;test pytest async

## 项目结构

```
api/
├── app/
│   ├── main.py             FastAPI app + lifespan + router wiring
│   ├── settings.py         Pydantic Settings(env-driven)
│   ├── deps.py             DI:db / openfga / feishu / s3 client(stub)
│   ├── routers/            REST endpoints,按业务域分包(stub)
│   │   ├── auth.py
│   │   ├── projects.py
│   │   ├── assets.py
│   │   ├── approvals.py
│   │   ├── webhooks.py
│   │   └── admin.py
│   ├── services/           业务逻辑(stub)
│   │   ├── permissions.py  openfga-sdk wrapper
│   │   ├── presign.py      boto3 presigned URL
│   │   ├── proxy.py        敏感目录 stream proxy + check
│   │   ├── audit.py        audit-schema 落库
│   │   └── feishu.py       飞书 API + bridge webhook handler
│   ├── db/
│   │   ├── tables.py       SQLAlchemy 2.x models(stub Base)
│   │   └── migrations/     alembic
│   ├── models/             Pydantic schemas(API I/O)
│   └── workers/main.py     arq tasks(转码 / 缩略图 stub)
├── tests/
│   └── test_healthz.py     smoke test(skeleton verify)
├── pyproject.toml          uv 包管理
├── alembic.ini
├── Dockerfile
├── docker-compose.yml      ms-api + ms-db + ms-redis + ms-worker
├── .env.example
└── README.md
```

## 本地启动(dev)

### Prereq
1. 现有 PoC 起着:`../poc/minio/docker-compose up -d`(MinIO + OpenFGA + nginx)
2. 安装 [uv](https://github.com/astral-sh/uv)

### 启动
```bash
cp .env.example .env
# 编辑 .env 填飞书 secret 等

# 本机直跑(快 iteration)
uv sync                                  # 装依赖
uv run uvicorn app.main:app --reload     # 启动 :8000
curl http://localhost:8000/healthz

# 跑测试
uv run pytest -v

# 跑 lint / type
uv run ruff check .
uv run mypy app
```

### docker-compose(集成 PoC network)
```bash
docker compose up -d
docker compose logs -f ms-api
curl http://localhost:8200/healthz       # 通过 ms-api 容器映射端口
```

## Phase B 实施路径(ADR-0006 §9)

| Phase | 内容 | 时间 |
|---|---|---|
| **B-1** | 本 skeleton + healthz + router stub(✅ 完成) | ✅ |
| **B-2** | DB schema + alembic migration + OpenFGA wrapper + MinIO presign service + 飞书 webhook handler + audit 落库 + 一个 e2e 流程(create project → upload presigned → grant download → audit) | 3-4 周 |
| **B-3** | React + AntD Pro 业务 UI + 飞书 H5 入口 | 4-6 周 |
| **B-4** | arq worker(ffmpeg 转码 / 缩略图 / dataset B)+ MinIO replication 灾备 | 2-3 周 |

## 与现有 PoC 的依赖关系

| PoC 组件 | 本 api 如何依赖 |
|---|---|
| `poc-pigsty-minio` | 业务后端 boto3 S3 client 调用 |
| `poc-openfga` | openfga-sdk grant/check/revoke |
| `poc-webhook`(临时)| **Phase B-2 整合入本 api `/api/v1/webhooks/minio` endpoint**,poc-webhook 退役 |
| `poc-presigner`(临时)| **Phase B-2 整合入本 api `/api/v1/assets/upload-url` endpoint**,poc-presigner 退役 |
| `poc-nginx` | 加 `/api/v1/` 反代到 ms-api:8200 |
| feishu bridge(待启动 Phase B 部署) | 通过 `FEISHU_BRIDGE_URL` env |

## 关联

- ADR-0005 §11.2 Gap 清单(P0:Gap 1/4/5/8/9/10/12)— 本 api 实施目标
- ADR-0006 § 9 Phase B 4 阶段拆解
- PoC openfga model: `../poc/openfga/store.fga.yaml`
- 飞书契约:MS-FB-001/002/004/007 v2(merged)+ MS-FB-008(issue #36 in flight)
