"""APScheduler wiring for background pipeline jobs.

``build_scheduler`` returns a *not-yet-started* :class:`BackgroundScheduler`
with the pipeline jobs registered; the caller (the app lifespan) owns start
and shutdown. Each job body funnels through :func:`app.pipeline.runner.run_job`,
so scheduled execution gets the same retry + ``PipelineRun`` bookkeeping as any
other invocation.
"""

from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import Engine

from app.pipeline.jobs import fetch_tw_quotes
from app.pipeline.runner import run_job


def build_scheduler(engine: Engine) -> BackgroundScheduler:
    """Build a scheduler registering the daily TW-quotes fetch.

    ``fetch_tw_quotes`` runs weekdays at 14:05 Asia/Taipei (just after the
    TWSE/TPEx close). ``misfire_grace_time`` tolerates a downtime window and
    ``coalesce`` collapses missed triggers into a single catch-up run rather
    than firing once per skipped slot.

    Returns the scheduler unstarted — the caller starts and shuts it down.
    """
    scheduler = BackgroundScheduler(timezone="Asia/Taipei")
    scheduler.add_job(
        run_job,
        trigger=CronTrigger(
            day_of_week="mon-fri", hour=14, minute=5, timezone="Asia/Taipei"
        ),
        args=(engine, "fetch_tw_quotes", fetch_tw_quotes),
        id="fetch_tw_quotes",
        misfire_grace_time=3600,
        coalesce=True,
    )
    return scheduler
