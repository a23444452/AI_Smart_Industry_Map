import os

# Disable the APScheduler wiring for the whole test session before any app
# module (and thus the `settings` singleton) is imported. Real background
# timers must never start under pytest; individual tests that exercise the
# scheduler opt in by monkeypatching `settings.scheduler_enabled`. Forced (not
# setdefault) so a developer's exported AISM_SCHEDULER_ENABLED can't leak in.
os.environ["AISM_SCHEDULER_ENABLED"] = "false"

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client() -> TestClient:
    with TestClient(create_app()) as client:
        yield client
