from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

from app.api import meta, topics
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
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "internal", "message": "伺服器發生錯誤"}},
        )

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    app.include_router(topics.router, prefix="/api")
    app.include_router(meta.router, prefix="/api")

    return app
