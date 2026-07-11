"""Tests for the pipeline runner — execution records + retry semantics.

The runner owns "run bookkeeping" only: it records a PipelineRun row and
retries the job function; it knows nothing about what a job does. Jobs
receive a SQLAlchemy Session and drive the DB themselves.
"""

from sqlalchemy.orm import Session

from app.db import models
from app.db.base import Base, make_engine
from app.pipeline.runner import run_job

NO_BACKOFF = (0, 0, 0)


def _make_db(tmp_path):
    eng = make_engine(f"{tmp_path}/t.db")
    Base.metadata.create_all(eng)
    return eng


def _runs(eng) -> list[models.PipelineRun]:
    with Session(eng) as s:
        return s.query(models.PipelineRun).order_by(models.PipelineRun.id).all()


def test_success_records_success_with_timestamps(tmp_path):
    eng = _make_db(tmp_path)

    def job(session):
        session.add(models.Company(ticker="2330", name="台積電", market="TW"))

    run_job(eng, "seed", job, backoff=NO_BACKOFF)

    rows = _runs(eng)
    assert len(rows) == 1
    run = rows[0]
    assert run.job_name == "seed"
    assert run.status == "success"
    assert run.started_at is not None
    assert run.finished_at is not None
    assert run.finished_at >= run.started_at
    assert run.error is None
    # fn side effects committed by the runner.
    with Session(eng) as s:
        assert s.get(models.Company, "2330") is not None


def test_always_failing_records_failed_after_retries(tmp_path):
    eng = _make_db(tmp_path)
    calls = {"n": 0}

    def job(session):
        calls["n"] += 1
        raise RuntimeError("boom-424242")

    run_job(eng, "flaky", job, retries=3, backoff=NO_BACKOFF)

    # 3 retries => 3 attempts total.
    assert calls["n"] == 3

    rows = _runs(eng)
    assert len(rows) == 1
    run = rows[0]
    assert run.status == "failed"
    assert run.finished_at is not None
    assert run.error is not None
    assert "boom-424242" in run.error  # original exception text preserved


def test_succeeds_on_second_attempt(tmp_path):
    eng = _make_db(tmp_path)
    calls = {"n": 0}

    def job(session):
        calls["n"] += 1
        if calls["n"] < 2:
            raise RuntimeError("transient")
        session.add(models.Company(ticker="2317", name="鴻海", market="TW"))

    run_job(eng, "retryable", job, retries=3, backoff=NO_BACKOFF)

    assert calls["n"] == 2  # failed once, then succeeded

    rows = _runs(eng)
    assert len(rows) == 1
    assert rows[0].status == "success"
    assert rows[0].error is None
    with Session(eng) as s:
        assert s.get(models.Company, "2317") is not None


def test_failed_attempt_does_not_leak_half_written_data(tmp_path):
    eng = _make_db(tmp_path)
    calls = {"n": 0}

    def job(session):
        calls["n"] += 1
        # write something, then blow up before returning
        session.add(models.Company(ticker="9999", name="半套", market="TW"))
        session.flush()
        if calls["n"] < 2:
            raise RuntimeError("rollback me")
        # second attempt: a different, clean row

    run_job(eng, "rollback", job, retries=3, backoff=NO_BACKOFF)

    rows = _runs(eng)
    assert rows[0].status == "success"
    # The failed attempt's partial write must have been rolled back; only
    # the successful attempt's row survives (one row, not two).
    with Session(eng) as s:
        companies = s.query(models.Company).all()
        assert len(companies) == 1
        assert companies[0].ticker == "9999"
