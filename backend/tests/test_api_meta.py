"""Tests for GET /api/meta/pipeline-status.

Reports, per job, the latest run's status plus the most recent successful
finish. A `running` row whose start is older than 2h is reported as `stale`
so a hard-killed leftover row can't mislead the UI into thinking a job is live.
"""

from datetime import timedelta

from sqlalchemy.orm import Session

from app.db import models
from app.db.base import _utcnow


def _engine(client):
    return client.app.state.engine


def _add_runs(client, runs: list[dict]) -> None:
    with Session(_engine(client)) as s:
        for r in runs:
            s.add(models.PipelineRun(**r))
        s.commit()


def _by_job(body: list[dict]) -> dict[str, dict]:
    return {item["job_name"]: item for item in body}


def test_pipeline_status_latest_status_and_last_success(client):
    now = _utcnow()
    _add_runs(
        client,
        [
            # fetch: an old success, then a newer failure → latest=failed,
            # last_success_at = the old success's finished_at.
            {
                "job_name": "fetch",
                "status": "success",
                "started_at": now - timedelta(hours=5),
                "finished_at": now - timedelta(hours=5),
            },
            {
                "job_name": "fetch",
                "status": "failed",
                "started_at": now - timedelta(hours=1),
                "finished_at": now - timedelta(hours=1),
                "error": "boom",
            },
            # seed: single success.
            {
                "job_name": "seed",
                "status": "success",
                "started_at": now - timedelta(minutes=10),
                "finished_at": now - timedelta(minutes=10),
            },
        ],
    )
    r = client.get("/api/meta/pipeline-status")
    assert r.status_code == 200
    body = r.json()
    assert {item["job_name"] for item in body} == {"fetch", "seed"}
    for item in body:
        assert set(item.keys()) == {
            "job_name",
            "last_status",
            "last_success_at",
            "last_finished_at",
        }

    jobs = _by_job(body)
    assert jobs["fetch"]["last_status"] == "failed"
    # latest run is the failed one → last_finished_at matches it, but the last
    # success timestamp still points at the older successful run.
    assert jobs["fetch"]["last_success_at"] is not None
    assert jobs["fetch"]["last_success_at"] != jobs["fetch"]["last_finished_at"]

    assert jobs["seed"]["last_status"] == "success"
    assert jobs["seed"]["last_success_at"] == jobs["seed"]["last_finished_at"]


def test_pipeline_status_stale_running(client):
    now = _utcnow()
    _add_runs(
        client,
        [
            # running for >2h → reported as stale
            {
                "job_name": "stuck",
                "status": "running",
                "started_at": now - timedelta(hours=3),
                "finished_at": None,
            },
            # running but recent → stays running
            {
                "job_name": "live",
                "status": "running",
                "started_at": now - timedelta(minutes=5),
                "finished_at": None,
            },
        ],
    )
    jobs = _by_job(client.get("/api/meta/pipeline-status").json())
    assert jobs["stuck"]["last_status"] == "stale"
    assert jobs["stuck"]["last_finished_at"] is None
    assert jobs["live"]["last_status"] == "running"


def test_pipeline_status_empty_when_no_runs(client):
    r = client.get("/api/meta/pipeline-status")
    assert r.status_code == 200
    assert r.json() == []
