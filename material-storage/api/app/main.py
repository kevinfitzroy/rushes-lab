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
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.routers import (
    admin, approvals, assets, auth, folders, groups, maintenance, projects,
    request_links, share, users, webhooks,
)
from app.settings import get_settings

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    log.info("starting material-storage-api", env=settings.env, version=__version__)

    # Phase B-2:wire 服务到 app.state
    from app.services.arq_pool import create_arq_pool
    from app.services.auth import create_auth_service
    from app.services.feishu_client import create_feishu_client
    from app.services.permissions import create_permissions_service
    from app.services.presign import PresignService

    app.state.permissions = await create_permissions_service(settings)
    app.state.presign = PresignService(settings)
    app.state.auth = await create_auth_service(settings)
    app.state.feishu_client = await create_feishu_client(settings)
    app.state.arq_pool = await create_arq_pool(settings)

    # 独立 redis client 给 maintenance banner 等轻量 KV 用(arq pool 不复用避免污染 queue keys)
    import redis.asyncio as redis_asyncio
    app.state.redis = redis_asyncio.from_url(str(settings.redis_url), decode_responses=True)

    # 注册 card-action handler(import 即注册 — services/feishu_card_handlers 等)
    # iter1:noop;iter2 起按 intent 注册具体 handler
    # 注:用 from-import 以免 `app` 名 shadow lifespan 参数 (Python 名字解析坑)
    from app.services import feishu_card_handlers as _h  # noqa: F401
    log.info("startup complete — permissions + presign + auth + feishu_client + arq + redis ready")

    yield

    log.info("shutting down")
    await app.state.permissions.close()
    await app.state.auth.close()
    await app.state.feishu_client.close()
    await app.state.arq_pool.aclose()
    await app.state.redis.aclose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="material-storage API",
        description="医美素材库业务后端 — ADR-0005 / ADR-0006 Phase B",
        version=__version__,
        lifespan=lifespan,
    )

    # CORS(给业务前端 React + 飞书 H5 内嵌 webview 用)
    # 默认从 web_app_base_url derive 同源 origin;`allow_credentials=True` 时
    # CORS spec 不允许 `*` wildcard,所以 explicit list 是必须的
    from urllib.parse import urlparse
    if settings.cors_allow_origins:
        allow_origins = [o.strip() for o in settings.cors_allow_origins.split(",") if o.strip()]
    else:
        parsed = urlparse(settings.web_app_base_url)
        allow_origins = [f"{parsed.scheme}://{parsed.netloc}"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # routers
    app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
    app.include_router(projects.router, prefix="/api/v1/projects", tags=["projects"])
    app.include_router(folders.router, prefix="/api/v1/folders", tags=["folders"])
    app.include_router(assets.router, prefix="/api/v1/assets", tags=["assets"])
    app.include_router(approvals.router, prefix="/api/v1/approvals", tags=["approvals"])
    app.include_router(users.router, prefix="/api/v1/users", tags=["users"])
    app.include_router(groups.router, prefix="/api/v1/groups", tags=["groups"])
    app.include_router(share.router, prefix="/api/v1/share", tags=["share"])
    app.include_router(webhooks.router, prefix="/api/v1/webhooks", tags=["webhooks"])
    app.include_router(admin.router, prefix="/api/v1/admin", tags=["admin"])
    app.include_router(maintenance.router, prefix="/api/v1/maintenance", tags=["maintenance"])
    app.include_router(request_links.router, prefix="/api/v1/request-links", tags=["request-links"])

    @app.get("/healthz", tags=["meta"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    # static / uppy demo + web SPA fallback
    import pathlib
    from fastapi import HTTPException
    from fastapi.responses import FileResponse

    static_dir = pathlib.Path(__file__).parent / "static"
    web_dir = static_dir / "web"

    # SPA catch-all:必须在 mount /static 之前定义,FastAPI 路由 order 优先
    # 行为:/static/web/{path} 命中本 route,若 path 是实际 file 则返 file,
    # 否则返 index.html(BrowserRouter 深链直接刷新支持)
    @app.get("/static/web/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        target = (web_dir / full_path).resolve()
        # 防 path traversal
        if not str(target).startswith(str(web_dir.resolve())):
            raise HTTPException(status_code=400)
        if target.is_file():
            return FileResponse(target)
        idx = web_dir / "index.html"
        if not idx.exists():
            raise HTTPException(status_code=404, detail="web dist not deployed")
        return FileResponse(idx)

    # 无尾斜杠 root(/static/web)— StaticFiles 默认会 307 到 /static/web/,
    # 走到 nginx 时 Location 把 /ms-static/ 漏丢 + http 降级,导致 SPA basename 错位崩。
    # 直接返 index.html,浏览器 URL 保持在 /ms-static/web,react-router basename 仍匹配。
    @app.get("/static/web", include_in_schema=False)
    async def spa_root_no_slash():
        idx = web_dir / "index.html"
        if not idx.exists():
            raise HTTPException(status_code=404, detail="web dist not deployed")
        return FileResponse(idx)

    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app


app = create_app()
