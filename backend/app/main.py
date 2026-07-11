from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.db.base import Base, make_engine
from app.pipeline.scheduler import build_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    # The scheduler runs only in the real service process; tests/CI disable it
    # via AISM_SCHEDULER_ENABLED=false so no background timers start under pytest.
    if settings.scheduler_enabled:
        engine = make_engine(settings.db_path)
        Base.metadata.create_all(engine)
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

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    return app
