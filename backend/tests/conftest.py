import os

# Disable the APScheduler wiring for the whole test session before any app
# module (and thus the `settings` singleton) is imported. Real background
# timers must never start under pytest; individual tests that exercise the
# scheduler opt in by monkeypatching `settings.scheduler_enabled`. Forced (not
# setdefault) so a developer's exported AISM_SCHEDULER_ENABLED can't leak in.
os.environ["AISM_SCHEDULER_ENABLED"] = "false"

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import create_app


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    # The lifespan always builds an engine at settings.db_path; point it at a
    # per-test tmp file so no test can ever write the real ./data/aism.db.
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "aism.db"))


@pytest.fixture
def client() -> TestClient:
    with TestClient(create_app()) as client:
        yield client
