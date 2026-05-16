"""material-storage 业务后端 — Phase B-1 skeleton(ADR-0006)。

模块布局:
  app/
    main.py         FastAPI app + lifespan + middleware
    settings.py     Pydantic Settings(env-driven)
    deps.py         Dependency Injection:db/openfga/feishu/s3 client
    routers/        REST API endpoints,按业务域分包
    services/       业务逻辑封装,被 routers 调
    db/             SQLAlchemy 2.x async + alembic migrations
    models/         Pydantic schemas(API I/O,非 DB ORM)
    workers/        arq tasks(转码 / 缩略图 / metadata)
"""
__version__ = "0.1.0"
