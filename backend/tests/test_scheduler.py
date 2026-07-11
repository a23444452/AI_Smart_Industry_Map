"""Task 7 — APScheduler wiring on the app lifespan.

Covers three behaviours:
  1. enabled → lifespan builds a running scheduler holding the
     ``fetch_tw_quotes`` job on a weekday 14:05 Asia/Taipei cron trigger.
  2. disabled → ``app.state.scheduler`` is None; no scheduler is started.
  3. lifespan exit → the scheduler is shut down.

TestClient must be entered as a context manager (``with TestClient(...)``);
a bare ``TestClient(app)`` does not trigger the lifespan.
"""

from apscheduler.triggers.cron import CronTrigger
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import create_app


def _field(trigger: CronTrigger, name: str) -> str:
    field = next(f for f in trigger.fields if f.name == name)
    return str(field)


def test_scheduler_enabled_registers_fetch_tw_quotes_job(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "scheduler_enabled", True)
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "aism.db"))

    app = create_app()
    with TestClient(app):
        scheduler = app.state.scheduler
        assert scheduler is not None
        assert scheduler.running

        job = scheduler.get_job("fetch_tw_quotes")
        assert job is not None

        trigger = job.trigger
        assert isinstance(trigger, CronTrigger)
        assert _field(trigger, "day_of_week") == "mon-fri"
        assert _field(trigger, "hour") == "14"
        assert _field(trigger, "minute") == "5"
        assert str(trigger.timezone) == "Asia/Taipei"

    # Lifespan has exited: the scheduler must be shut down.
    assert not scheduler.running


def test_scheduler_disabled_leaves_no_scheduler(monkeypatch):
    monkeypatch.setattr(settings, "scheduler_enabled", False)

    app = create_app()
    with TestClient(app):
        assert getattr(app.state, "scheduler", None) is None
