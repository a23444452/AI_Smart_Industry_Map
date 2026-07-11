"""Task 7 — APScheduler wiring on the app lifespan.

Covers four behaviours:
  1. enabled → lifespan builds a running scheduler holding the
     ``fetch_tw_quotes`` job on a weekday 14:05 Asia/Taipei cron trigger.
  2. disabled → ``app.state.scheduler`` is None; no scheduler is started.
  3. lifespan exit → the scheduler is shut down.
  4. both modes → ``app.state.engine`` exists with the schema created, so the
     API layer has a single dependency point regardless of scheduler mode.

TestClient must be entered as a context manager (``with TestClient(...)``);
a bare ``TestClient(app)`` does not trigger the lifespan. The DB path is
isolated to tmp_path by conftest's autouse ``_tmp_db`` fixture.
"""

from apscheduler.triggers.cron import CronTrigger
from fastapi.testclient import TestClient
from sqlalchemy import inspect

from app.core.config import settings
from app.main import create_app


def _field(trigger: CronTrigger, name: str) -> str:
    field = next(f for f in trigger.fields if f.name == name)
    return str(field)


def test_scheduler_enabled_registers_fetch_tw_quotes_job(monkeypatch):
    monkeypatch.setattr(settings, "scheduler_enabled", True)

    app = create_app()
    with TestClient(app):
        scheduler = app.state.scheduler
        assert scheduler is not None
        assert scheduler.running

        job = scheduler.get_job("fetch_tw_quotes")
        assert job is not None
        # Job body is run_job(engine, "fetch_tw_quotes", fetch_tw_quotes).
        assert job.args[1] == "fetch_tw_quotes"
        assert job.misfire_grace_time == 3600
        assert job.coalesce is True

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


def test_engine_mounted_with_schema_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "scheduler_enabled", False)

    app = create_app()
    with TestClient(app):
        engine = getattr(app.state, "engine", None)
        assert engine is not None
        # Schema was created: core tables must exist and be queryable.
        tables = set(inspect(engine).get_table_names())
        assert "pipeline_runs" in tables
