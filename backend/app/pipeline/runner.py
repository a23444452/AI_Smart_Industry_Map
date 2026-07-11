"""Pipeline runner — execution bookkeeping and retry.

The runner owns one concern only: record a :class:`PipelineRun` row and retry
the job callable. It knows nothing about what a job does. A job is a callable
``fn(session)`` that receives a SQLAlchemy :class:`~sqlalchemy.orm.Session` and
drives the DB itself; the runner commits on success.

Transaction contract: a job fn must NOT call ``session.commit()`` or
``session.rollback()`` itself — the runner owns the transaction boundary.
If a fn commits mid-job and then fails, the already-committed writes cannot
be rolled back, so the retry starts from a dirty state. This is a documented
limitation (covered by tests); job implementations (e.g. Task 6's
``fetch_tw_quotes``) must only stage changes on the session and leave
commit/rollback to the runner.

A failed job never propagates: jobs run under a scheduler / API process that
must stay alive, so exhausted retries are recorded as ``failed`` and logged,
not re-raised.
"""

import time
from collections.abc import Callable, Sequence

from loguru import logger
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.db.base import _utcnow
from app.db.models import PipelineRun

JobFn = Callable[[Session], None]


def run_job(
    engine: Engine,
    name: str,
    fn: JobFn,
    retries: int = 3,
    backoff: Sequence[float] = (1, 4, 16),
) -> PipelineRun:
    """Execute ``fn`` with retry, recording a :class:`PipelineRun`.

    A single ``running`` row is committed up front so in-flight state is
    visible, then updated to ``success`` / ``failed`` when the job settles.

    Args:
        engine: SQLAlchemy engine to open the bookkeeping/job session on.
        name: Job name stored on the run record.
        fn: Callable ``fn(session)``. It must not commit/rollback the session
            itself — the runner owns the transaction boundary (see module
            docstring for the full contract).
        retries: Maximum attempts. Values <= 0 record an immediate ``failed``
            run without calling ``fn``.
        backoff: Per-attempt sleep seconds; ``backoff[i]`` is slept after the
            ``i``-th failed attempt before retrying. A sequence shorter than
            needed falls back to no sleep for the missing entries.

    Returns:
        The persisted :class:`PipelineRun`, detached from its session with all
        attributes loaded — callers can read ``status``/``error``/etc. directly.
    """
    with Session(engine, expire_on_commit=False) as session:
        run = PipelineRun(job_name=name, status="running", started_at=_utcnow())
        session.add(run)
        session.commit()  # make the running state visible immediately

        last_exc: Exception | None = None
        for attempt in range(retries):
            try:
                fn(session)
                session.commit()  # persist the job's own writes
            except Exception as exc:  # noqa: BLE001 - job failures must not escape
                # Discard this attempt's half-written data so retries start clean.
                session.rollback()
                last_exc = exc
                logger.warning(
                    "job {!r} attempt {}/{} failed: {}",
                    name,
                    attempt + 1,
                    retries,
                    exc,
                )
                if attempt + 1 < retries:
                    time.sleep(backoff[attempt] if attempt < len(backoff) else 0)
            else:
                run.status = "success"
                run.finished_at = _utcnow()
                session.commit()
                logger.info("job {!r} succeeded on attempt {}", name, attempt + 1)
                break
        else:
            # Retries exhausted (or retries <= 0): record failure, never re-raise.
            run.status = "failed"
            run.error = str(last_exc) if last_exc is not None else "no attempts run"
            run.finished_at = _utcnow()
            session.commit()
            logger.error(
                "job {!r} failed after {} attempts: {}", name, retries, run.error
            )

        # Hand back a fully-loaded, detached row the caller can read directly.
        session.refresh(run)
        session.expunge(run)
        return run
