"""AI 分析 API 三端點測試——analyze / analyses/{id} / leaderboard.

`client` fixture 跑真實 lifespan 對 per-test tmp DB，engine 掛在
`app.state.engine`。POST /analyze 在 TestClient 下背景任務同步執行——POST 回應後
背景 run_analysis 已跑完，緊接 GET 即應為 done（provider 預設 mock，確定性輸出）。
所有斷言不打真實 API。
"""

from datetime import timedelta

from sqlalchemy.orm import Session

from app.db import models
from app.db.base import utcnow
from app.llm.provider import ASPECTS


def _engine(client):
    return client.app.state.engine


def _add(client, rows: list) -> None:
    with Session(_engine(client)) as s:
        for r in rows:
            s.add(r)
        s.commit()


def _company(ticker="2330", name="台積電"):
    return models.Company(ticker=ticker, name=name, market="TW")


# ── POST /api/ai/analyze ─────────────────────────────────────────────────────
def test_analyze_creates_and_runs_to_done(client):
    _add(client, [_company()])

    resp = client.post("/api/ai/analyze", json={"ticker": "2330", "mode": "全面檢視"})
    assert resp.status_code == 202
    aid = resp.json()["analysis_id"]
    assert isinstance(aid, int)

    # TestClient 同步跑背景任務——此時已 done（mock provider）。
    got = client.get(f"/api/ai/analyses/{aid}")
    assert got.status_code == 200
    body = got.json()
    assert body["status"] == "done"
    assert set(body["scores"]) == set(ASPECTS)
    # 確定性：每面向 60-95 整數，total 為五面向平均（四捨五入到 1 位）。
    for v in body["scores"].values():
        assert isinstance(v, int) and 60 <= v <= 95
    expected_total = round(sum(body["scores"].values()) / len(body["scores"]), 1)
    assert body["total"] == expected_total
    assert body["model"] == "mock"
    assert body["error"] is None
    assert body["name"] == "台積電"
    assert body["ticker"] == "2330"
    assert body["mode"] == "全面檢視"
    assert body["created_at"].endswith("Z")


def test_analyze_persists_pending_row(client):
    # 落地檢查：背景任務跑完後，DB 確有一列且非 pending。
    _add(client, [_company()])
    resp = client.post("/api/ai/analyze", json={"ticker": "2330", "mode": "近期觀察"})
    aid = resp.json()["analysis_id"]
    with Session(_engine(client)) as s:
        row = s.get(models.AiAnalysis, aid)
    assert row is not None
    assert row.ticker == "2330"
    assert row.mode == "近期觀察"


def test_analyze_invalid_mode_422(client):
    _add(client, [_company()])
    resp = client.post("/api/ai/analyze", json={"ticker": "2330", "mode": "亂填"})
    assert resp.status_code == 422


def test_analyze_missing_ticker_field_422(client):
    resp = client.post("/api/ai/analyze", json={"mode": "全面檢視"})
    assert resp.status_code == 422


def test_analyze_unknown_ticker_404(client):
    resp = client.post("/api/ai/analyze", json={"ticker": "0000", "mode": "全面檢視"})
    assert resp.status_code == 404
    assert resp.json() == {
        "error": {"code": "not_found", "message": "找不到此公司"}
    }


def test_analyze_conflict_when_pending_exists(client):
    _add(client, [_company()])
    # 先插一列 pending（同 ticker+mode），再 POST → 409。
    _add(
        client,
        [models.AiAnalysis(ticker="2330", mode="全面檢視", status="pending")],
    )
    resp = client.post("/api/ai/analyze", json={"ticker": "2330", "mode": "全面檢視"})
    assert resp.status_code == 409
    assert resp.json() == {
        "error": {"code": "conflict", "message": "該個股同模式分析進行中，請稍候"}
    }


def test_analyze_conflict_when_running_exists(client):
    _add(client, [_company()])
    _add(
        client,
        [models.AiAnalysis(ticker="2330", mode="全面檢視", status="running")],
    )
    resp = client.post("/api/ai/analyze", json={"ticker": "2330", "mode": "全面檢視"})
    assert resp.status_code == 409


def test_analyze_no_conflict_across_modes(client):
    # 同 ticker 不同 mode 的 pending 不擋——只擋同 ticker+同 mode。
    _add(client, [_company()])
    _add(
        client,
        [models.AiAnalysis(ticker="2330", mode="近期觀察", status="pending")],
    )
    resp = client.post("/api/ai/analyze", json={"ticker": "2330", "mode": "全面檢視"})
    assert resp.status_code == 202


def test_analyze_no_conflict_when_prior_done(client):
    # 舊的 done 列不擋新請求。
    _add(client, [_company()])
    _add(
        client,
        [models.AiAnalysis(ticker="2330", mode="全面檢視", status="done", total=80.0)],
    )
    resp = client.post("/api/ai/analyze", json={"ticker": "2330", "mode": "全面檢視"})
    assert resp.status_code == 202


# ── GET /api/ai/analyses/{id} ────────────────────────────────────────────────
def test_get_analysis_not_found_404(client):
    resp = client.get("/api/ai/analyses/999999")
    assert resp.status_code == 404
    assert resp.json() == {
        "error": {"code": "not_found", "message": "找不到此分析"}
    }


def test_get_analysis_pending_nullable_fields(client):
    # 誠實回報 nullable：pending 列的 scores/reasons/summary/total/model/error 皆 null。
    _add(client, [_company()])
    _add(
        client,
        [models.AiAnalysis(ticker="2330", mode="全面檢視", status="pending")],
    )
    with Session(_engine(client)) as s:
        aid = s.query(models.AiAnalysis).first().id
    body = client.get(f"/api/ai/analyses/{aid}").json()
    assert body["status"] == "pending"
    assert body["scores"] is None
    assert body["reasons"] is None
    assert body["summary"] is None
    assert body["total"] is None
    assert body["model"] is None
    assert body["error"] is None
    assert body["name"] == "台積電"


def test_get_analysis_name_null_when_company_missing(client):
    # company 不存在時 name 誠實為 null（不炸）。
    _add(
        client,
        [models.AiAnalysis(ticker="0000", mode="全面檢視", status="pending")],
    )
    with Session(_engine(client)) as s:
        aid = s.query(models.AiAnalysis).first().id
    body = client.get(f"/api/ai/analyses/{aid}").json()
    assert body["name"] is None
    assert body["ticker"] == "0000"


# ── GET /api/ai/leaderboard ──────────────────────────────────────────────────
def _done(ticker, mode, total, days_ago=0):
    return models.AiAnalysis(
        ticker=ticker,
        mode=mode,
        status="done",
        total=total,
        scores={a: 80 for a in ASPECTS},
        model="mock",
        created_at=utcnow() - timedelta(days=days_ago),
    )


def test_leaderboard_empty(client):
    resp = client.get("/api/ai/leaderboard")
    assert resp.status_code == 200
    assert resp.json() == {"items": []}


def test_leaderboard_strong_default_sort_desc(client):
    _add(client, [_company("2330", "台積電"), _company("2317", "鴻海"), _company("3008", "大立光")])
    _add(
        client,
        [
            _done("2330", "全面檢視", 90.0),
            _done("2317", "全面檢視", 70.0),
            _done("3008", "全面檢視", 80.0),
        ],
    )
    items = client.get("/api/ai/leaderboard").json()["items"]
    assert [it["ticker"] for it in items] == ["2330", "3008", "2317"]
    assert [it["rank"] for it in items] == [1, 2, 3]
    assert items[0]["name"] == "台積電"
    assert items[0]["total"] == 90.0
    assert set(items[0]["scores"]) == set(ASPECTS)
    assert items[0]["model"] == "mock"
    assert items[0]["created_at"].endswith("Z")


def test_leaderboard_weak_sort_asc(client):
    _add(client, [_company("2330"), _company("2317", "鴻海")])
    _add(
        client,
        [_done("2330", "全面檢視", 90.0), _done("2317", "全面檢視", 70.0)],
    )
    items = client.get("/api/ai/leaderboard?sort=weak").json()["items"]
    assert [it["ticker"] for it in items] == ["2317", "2330"]


def test_leaderboard_latest_done_per_ticker(client):
    # 每 ticker 取最新一筆 done：舊列 total=50、新列 total=95，榜上應是 95。
    _add(client, [_company("2330")])
    _add(
        client,
        [
            _done("2330", "全面檢視", 50.0, days_ago=5),
            _done("2330", "全面檢視", 95.0, days_ago=0),
        ],
    )
    items = client.get("/api/ai/leaderboard").json()["items"]
    assert len(items) == 1
    assert items[0]["total"] == 95.0


def test_leaderboard_mode_filter(client):
    _add(client, [_company("2330"), _company("2317", "鴻海")])
    _add(
        client,
        [
            _done("2330", "近期觀察", 88.0),
            _done("2317", "全面檢視", 99.0),
        ],
    )
    items = client.get("/api/ai/leaderboard?mode=近期觀察").json()["items"]
    assert [it["ticker"] for it in items] == ["2330"]
    assert items[0]["mode"] == "近期觀察"


def test_leaderboard_invalid_mode_422(client):
    resp = client.get("/api/ai/leaderboard?mode=亂填")
    assert resp.status_code == 422


def test_leaderboard_invalid_sort_422(client):
    resp = client.get("/api/ai/leaderboard?sort=nope")
    assert resp.status_code == 422


def test_leaderboard_excludes_non_done(client):
    # pending/running/failed 不入榜。
    _add(client, [_company("2330")])
    _add(
        client,
        [models.AiAnalysis(ticker="2330", mode="全面檢視", status="failed", total=99.0)],
    )
    items = client.get("/api/ai/leaderboard").json()["items"]
    assert items == []


def test_leaderboard_top_50_cap(client):
    companies = [_company(f"{1000 + i}", f"C{i}") for i in range(60)]
    _add(client, companies)
    _add(client, [_done(f"{1000 + i}", "全面檢視", float(i)) for i in range(60)])
    items = client.get("/api/ai/leaderboard").json()["items"]
    assert len(items) == 50
    # strong：total 最高的 50 檔（i=10..59），第一名 total=59。
    assert items[0]["total"] == 59.0
    assert items[-1]["total"] == 10.0
