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


def test_returned_run_is_readable_after_success(tmp_path):
    # I-1: the returned PipelineRun must be detached with attributes loaded —
    # reading it outside any session must not raise DetachedInstanceError.
    eng = _make_db(tmp_path)

    run = run_job(eng, "ok", lambda session: None, backoff=NO_BACKOFF)

    assert run.id is not None
    assert run.job_name == "ok"
    assert run.status == "success"
    assert run.error is None
    assert run.started_at is not None
    assert run.finished_at is not None


def test_returned_run_is_readable_after_failure(tmp_path):
    eng = _make_db(tmp_path)

    def job(session):
        raise RuntimeError("boom-detached")

    run = run_job(eng, "bad", job, retries=2, backoff=NO_BACKOFF)

    assert run.id is not None
    assert run.status == "failed"
    assert "boom-detached" in run.error
    assert run.finished_at is not None


def test_fn_committing_mid_job_leaks_data_documented_limitation(tmp_path):
    """固化交易契約：fn 不得自行 commit（runner 擁有交易邊界）。

    Documented limitation: 若 fn 違反契約在中途 commit 後才失敗，已 commit
    的資料無法被 runner 的 rollback 回收，重試會從髒狀態開始。本測試固化
    此行為，Task 6 起的 job 實作必須遵守「只 stage、不 commit」。
    """
    eng = _make_db(tmp_path)
    calls = {"n": 0}

    def contract_violating_job(session):
        calls["n"] += 1
        session.add(
            models.Company(
                ticker=f"T{calls['n']}", name=f"第{calls['n']}次", market="TW"
            )
        )
        session.commit()  # 違反契約：fn 自行 commit
        if calls["n"] < 2:
            raise RuntimeError("fail after own commit")

    run = run_job(eng, "dirty", contract_violating_job, retries=3, backoff=NO_BACKOFF)

    assert run.status == "success"
    with Session(eng) as s:
        tickers = {c.ticker for c in s.query(models.Company).all()}
    # 第一次 attempt 已 commit 的 T1 沒有被回收 —— 髒狀態殘留，這正是
    # 契約禁止 fn 自行 commit 的原因。
    assert tickers == {"T1", "T2"}


def test_backoff_shorter_than_retries_falls_back_to_no_sleep(tmp_path):
    # M-4: backoff 序列比 retries 短時不可 IndexError，缺項視為不 sleep。
    eng = _make_db(tmp_path)
    calls = {"n": 0}

    def job(session):
        calls["n"] += 1
        raise RuntimeError("always")

    run = run_job(eng, "short-backoff", job, retries=3, backoff=(0,))

    assert calls["n"] == 3
    assert run.status == "failed"


def test_retries_zero_records_failed_without_calling_fn(tmp_path):
    # M-4: retries <= 0 防禦分支 —— 不呼叫 fn，直接記 failed。
    eng = _make_db(tmp_path)
    calls = {"n": 0}

    def job(session):
        calls["n"] += 1

    run = run_job(eng, "no-attempts", job, retries=0, backoff=NO_BACKOFF)

    assert calls["n"] == 0
    assert run.status == "failed"
    assert run.error == "no attempts run"
    assert run.finished_at is not None


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
