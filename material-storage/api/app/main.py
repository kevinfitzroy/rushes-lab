"""FastAPI app entry — lifespan + middleware + router wiring。

启动:
  uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

生产:
  uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
"""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.routers import admin, approvals, assets, auth, projects, webhooks
from app.settings import get_settings

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    log.info("starting material-storage-api", env=settings.env, version=__version__)

    # TODO Phase B-1:
    #   - connect db pool
    #   - connect redis
    #   - connect openfga(verify store / model id)
    #   - connect feishu bridge(health check)
    #   - connect MinIO(health check)
    #   挂到 app.state
    log.info("startup complete")

    yield

    log.info("shutting down")
    # TODO: cleanup pools


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="material-storage API",
        description="医美素材库业务后端 — ADR-0005 / ADR-0006 Phase B",
        version=__version__,
        lifespan=lifespan,
    )

    # CORS(给业务前端 React + 飞书 H5 内嵌 webview 用)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],   # TODO Phase B:严格限制到业务前端 origin
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # routers
    app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
    app.include_router(projects.router, prefix="/api/v1/projects", tags=["projects"])
    app.include_router(assets.router, prefix="/api/v1/assets", tags=["assets"])
    app.include_router(approvals.router, prefix="/api/v1/approvals", tags=["approvals"])
    app.include_router(webhooks.router, prefix="/api/v1/webhooks", tags=["webhooks"])
    app.include_router(admin.router, prefix="/api/v1/admin", tags=["admin"])

    @app.get("/healthz", tags=["meta"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return app


app = create_app()
