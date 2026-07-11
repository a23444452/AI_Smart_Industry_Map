"""GET /api/meta/pipeline-status — per-job pipeline health for the UI.

For each job name we report the latest run's status and finish time plus the
most recent *successful* finish. A ``running`` row whose ``started_at`` is more
than :data:`STALE_AFTER` old is reported as ``"stale"`` — a hard-killed process
can leave a ``running`` row behind, and reporting it as live would mislead the
UI into thinking a job is still in flight.
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.serializers import to_utc_iso
from app.db.base import _utcnow
from app.db.models import PipelineRun

router = APIRouter(prefix="/meta", tags=["meta"])

STALE_AFTER = timedelta(hours=2)


class PipelineStatusItem(BaseModel):
    job_name: str
    last_status: str
    # 時間戳輸出為 UTC ISO8601 帶 Z 尾碼字串（見 app.api.serializers.to_utc_iso）；
    # 儲存的 naive datetime 若交由 Pydantic 自動序列化不會帶時區標記，前端無從辨識。
    last_success_at: str | None
    last_finished_at: str | None


def _resolve_status(latest: PipelineRun, now: datetime) -> str:
    if (
        latest.status == "running"
        and latest.started_at is not None
        and now - latest.started_at > STALE_AFTER
    ):
        return "stale"
    return latest.status


@router.get("/pipeline-status", response_model=list[PipelineStatusItem])
def get_pipeline_status(request: Request) -> list[PipelineStatusItem]:
    engine = request.app.state.engine
    now = _utcnow()
    # Newest first per job (id is a monotonic surrogate for insertion order), so
    # the first row seen for each job_name is its latest run. Single scan → no
    # per-job query.
    # TODO: 若 job 高頻化（pipeline_runs 列數大增），改用 window 查詢
    #       （ROW_NUMBER() OVER (PARTITION BY job_name ORDER BY id DESC)）
    #       並加 (job_name, id) 索引，避免全表掃描。
    stmt = select(PipelineRun).order_by(PipelineRun.id.desc())

    with Session(engine) as session:
        runs = session.execute(stmt).scalars().all()

    latest_by_job: dict[str, PipelineRun] = {}
    last_success_by_job: dict[str, datetime | None] = {}
    for run in runs:
        if run.job_name not in latest_by_job:
            latest_by_job[run.job_name] = run
        if (
            run.status == "success"
            and run.job_name not in last_success_by_job
        ):
            last_success_by_job[run.job_name] = run.finished_at

    return [
        PipelineStatusItem(
            job_name=job_name,
            last_status=_resolve_status(latest, now),
            last_success_at=to_utc_iso(last_success_by_job.get(job_name)),
            last_finished_at=to_utc_iso(latest.finished_at),
        )
        for job_name, latest in latest_by_job.items()
    ]
