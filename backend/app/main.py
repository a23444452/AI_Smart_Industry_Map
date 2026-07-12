from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

from app.api import ai, companies, daily, meta, search, topic_map, topics
from app.core.config import settings
from app.db.base import Base, make_engine
from app.pipeline.scheduler import build_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Engine + schema are always mounted on app.state — the API layer depends
    # on app.state.engine as its single access point, in every mode.
    engine = make_engine(settings.db_path)
    Base.metadata.create_all(engine)
    app.state.engine = engine

    # The scheduler runs only in the real service process; tests/CI disable it
    # via AISM_SCHEDULER_ENABLED=false so no background timers start under pytest.
    if settings.scheduler_enabled:
        scheduler = build_scheduler(engine)
        scheduler.start()
        app.state.scheduler = scheduler
        try:
            yield
        finally:
            scheduler.shutdown(wait=False)
    else:
        app.state.scheduler = None
        yield


def create_app() -> FastAPI:
    app = FastAPI(title="AI Smart Industry Map", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception):
        # Last-resort handler: log the real cause server-side, but never leak
        # internal details (stack, SQL, paths) to the client.
        logger.exception("unhandled error on {} {}", request.method, request.url.path)
        # This handler is served by Starlette's ServerErrorMiddleware, which
        # wraps the app OUTSIDE CORSMiddleware — its response never passes
        # through CORS processing. Without these headers a browser blocks the
        # 500 body and the frontend can't read the friendly error message, so
        # we echo whitelisted Origins manually (Vary: Origin keeps shared
        # caches from serving one origin's header to another).
        headers = {}
        origin = request.headers.get("origin")
        if origin is not None and (
            origin in settings.cors_origins or "*" in settings.cors_origins
        ):
            headers = {
                "Access-Control-Allow-Origin": origin,
                "Vary": "Origin",
            }
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "internal", "message": "伺服器發生錯誤"}},
            headers=headers,
        )

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    app.include_router(topics.router, prefix="/api")
    app.include_router(topic_map.router, prefix="/api")
    app.include_router(daily.router, prefix="/api")
    app.include_router(meta.router, prefix="/api")
    app.include_router(companies.router, prefix="/api")
    app.include_router(ai.router, prefix="/api")
    app.include_router(search.router, prefix="/api")

    return app
