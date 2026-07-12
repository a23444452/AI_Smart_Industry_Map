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

from app.pipeline.jobs import fetch_institutional, fetch_tw_quotes
from app.pipeline.jobs_daily import fetch_indices, fetch_market_stats, fetch_mops
from app.pipeline.runner import run_job


def build_scheduler(engine: Engine) -> BackgroundScheduler:
    """Build a scheduler registering the daily TW-quotes and institutional fetches.

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

    # ``fetch_institutional`` fires twice on weekdays — 16:10 and 17:10
    # Asia/Taipei. T86 publishes shortly after the 13:30 close but the exact
    # time drifts; the second pass is a cheap idempotent catch-up (upsert) that
    # backstops a late/missed first publish. Same misfire/coalesce policy as the
    # quotes job.
    for hour in (16, 17):
        scheduler.add_job(
            run_job,
            trigger=CronTrigger(
                day_of_week="mon-fri", hour=hour, minute=10, timezone="Asia/Taipei"
            ),
            args=(engine, "fetch_institutional", fetch_institutional),
            id=f"fetch_institutional_{hour:02d}10",
            misfire_grace_time=3600,
            coalesce=True,
        )

    # 每日焦點三 job（S5）。共用 misfire/coalesce 政策。
    #
    # ``fetch_indices``：盤中每 15 分鐘刷新指數快照，平日 08–22 時（涵蓋台股盤前、
    # 台股盤中、美股/日經時段的粗略觀察窗）。
    scheduler.add_job(
        run_job,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour="8-22",
            minute="*/15",
            timezone="Asia/Taipei",
        ),
        args=(engine, "fetch_indices", fetch_indices),
        id="fetch_indices",
        misfire_grace_time=3600,
        coalesce=True,
    )

    # ``fetch_market_stats``：BFI82U 法人金額與信用交易餘額於收盤後陸續公布、
    # 確切時間漂移，故三發（16:20 / 17:20 / 21:45）冪等 upsert 補抓晚出的資料。
    for hour, minute in ((16, 20), (17, 20), (21, 45)):
        scheduler.add_job(
            run_job,
            trigger=CronTrigger(
                day_of_week="mon-fri",
                hour=hour,
                minute=minute,
                timezone="Asia/Taipei",
            ),
            args=(engine, "fetch_market_stats", fetch_market_stats),
            id=f"fetch_market_stats_{hour:02d}{minute:02d}",
            misfire_grace_time=3600,
            coalesce=True,
        )

    # ``fetch_mops``：重大訊息**每日** 19:10（含週末——公司於假日亦可能發布公告）。
    # 無 day_of_week 限制即為每天。
    scheduler.add_job(
        run_job,
        trigger=CronTrigger(hour=19, minute=10, timezone="Asia/Taipei"),
        args=(engine, "fetch_mops", fetch_mops),
        id="fetch_mops",
        misfire_grace_time=3600,
        coalesce=True,
    )
    return scheduler
