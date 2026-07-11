"""Tests for GET /api/topics/{slug} — 題材詳情（卡片 meta＋三週期 treemap＋籌碼訊號）.

`client` fixture 跑真實 lifespan 對 per-test tmp DB，並把 engine 掛在
`app.state.engine`；測試透過同一 engine seed（真實 seeds via load_seeds ＋手插
已知 quotes / institutional_flows / pipeline_runs），API 讀到的就是測試寫入的。
"""

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import models
from app.db.base import _utcnow
from app.db.seed import load_seeds

SLUG = "silicon-photonics"


def _d(days_ago: int) -> str:
    """今日（UTC）往回 ``days_ago`` 日曆日的 ISO 日期。

    fixture 日期以「今日」為基準：quotes/flows 查詢有時間下界（60／21 日曆日），
    固定日期會隨真實時間流逝掉出視窗，測試變成定時炸彈。
    """
    return (_utcnow().date() - timedelta(days=days_ago)).isoformat()


def _engine(client):
    return client.app.state.engine


def _seed_real(client) -> None:
    with Session(_engine(client)) as s:
        load_seeds(settings.seeds_dir, s)
        s.commit()


def _add_quotes(client, rows: list[dict]) -> None:
    with Session(_engine(client)) as s:
        for r in rows:
            s.add(models.QuoteDaily(**r))
        s.commit()


def _add_flows(client, rows: list[dict]) -> None:
    with Session(_engine(client)) as s:
        for r in rows:
            s.add(models.InstitutionalFlow(**r))
        s.commit()


def _add_run(client, **kwargs) -> None:
    with Session(_engine(client)) as s:
        s.add(models.PipelineRun(**kwargs))
        s.commit()


def _item(items: list[dict], ticker: str) -> dict:
    return next(i for i in items if i["ticker"] == ticker)


# ── case 1: 卡片 meta 欄位齊全且與 seed 一致 ──────────────────────────────
def test_card_meta_matches_seed(client):
    _seed_real(client)
    r = client.get(f"/api/topics/{SLUG}")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {
        "slug",
        "title",
        "description",
        "metrics",
        "verified_at",
        "treemap",
        "chip_signals",
        "quotes_updated_at",
    }
    assert body["slug"] == SLUG
    assert body["title"] == "光通訊｜矽光子與 CPO"
    assert "CPO" in body["description"]
    assert body["verified_at"] == "2026-07-11"
    assert body["metrics"]["cagr"] == "45%+"
    assert body["metrics"]["tech_core"] == "CPO 共同封裝"


# ── case 2: treemap.day 取每檔最新日 change_pct（插多日驗證取最新；round 2）──
def test_treemap_day_uses_latest_day_change_pct_rounded(client):
    _seed_real(client)
    _add_quotes(
        client,
        [
            # 舊日應被忽略；最新日的原始值 -2.028397… → 伺服端 round 2 → -2.03
            {"ticker": "2330", "date": _d(1), "close": 100.0, "change_pct": 99.0},
            {
                "ticker": "2330",
                "date": _d(0),
                "close": 98.0,
                "change_pct": -2.028397565922921,
            },
        ],
    )
    day = client.get(f"/api/topics/{SLUG}").json()["treemap"]["day"]
    item = _item(day, "2330")
    assert item["change_pct"] == -2.03
    assert item["name"] == "台積電"


def _descending_quotes(ticker: str, closes: list[float], change_pct_newest=None):
    """closes[0] 為最新日；日期由今日往回每日 -1（僅需 per-ticker 排序）。"""
    rows = []
    for i, close in enumerate(closes):
        row = {"ticker": ticker, "date": _d(i), "close": close}
        if i == 0 and change_pct_newest is not None:
            row["change_pct"] = change_pct_newest
        rows.append(row)
    return rows


# ── case 3+4: treemap.week / month 數值（round 2）與不足天數 → null ─────────
def test_treemap_week_and_month_values_and_insufficient_null(client):
    _seed_real(client)
    # 2330：22 個交易日，close 由最新 121 往回每日 -1（index5=116, index21=100）
    #   week  = (121/116 - 1)*100 = 4.31
    #   month = (121/100 - 1)*100 = 21.0
    closes_2330 = [121.0 - i for i in range(22)]
    # 3443：只有 3 日 → week/month 皆 null，但 day 仍取最新 change_pct
    _add_quotes(
        client,
        _descending_quotes("2330", closes_2330, change_pct_newest=-2.03)
        + _descending_quotes("3443", [50.0, 49.0, 48.0], change_pct_newest=1.5),
    )
    tm = client.get(f"/api/topics/{SLUG}").json()["treemap"]

    assert _item(tm["week"], "2330")["change_pct"] == 4.31
    assert _item(tm["month"], "2330")["change_pct"] == 21.0
    assert _item(tm["day"], "2330")["change_pct"] == -2.03

    # 不足 6 日 → week null；不足 22 日 → month null
    assert _item(tm["week"], "3443")["change_pct"] is None
    assert _item(tm["month"], "3443")["change_pct"] is None
    assert _item(tm["day"], "3443")["change_pct"] == 1.5


def test_treemap_week_boundary_exactly_six_days(client):
    _seed_real(client)
    # 恰好 6 日：index5 存在 → week 有值；仍不足 22 → month null
    #   close 最新 110、index5（第6日）100 → week = 10.0
    _add_quotes(client, _descending_quotes("2330", [110.0, 108, 106, 104, 102, 100.0]))
    tm = client.get(f"/api/topics/{SLUG}").json()["treemap"]
    assert _item(tm["week"], "2330")["change_pct"] == 10.0
    assert _item(tm["month"], "2330")["change_pct"] is None


# ── case 5: chip_signals — 每檔最新 5 筆 flows，SUM>0 計入 ─────────────────
def test_chip_signals_counts_and_updated_at(client):
    _seed_real(client)
    # 2330：6 筆 flows；最新 5 筆各 foreign_net=+100 / trust_net=+50 → 皆計入。
    #   最舊一筆（6 日前）巨額負值：若誤取 6 筆 SUM 會翻負 → 驗證只取最新 5 筆。
    rows = []
    dates = [_d(1), _d(2), _d(3), _d(4), _d(5)]
    for d in dates:
        rows.append(
            {"ticker": "2330", "date": d, "foreign_net": 100, "trust_net": 50}
        )
    rows.append(
        {
            "ticker": "2330",
            "date": _d(6),
            "foreign_net": -1_000_000,
            "trust_net": -1_000_000,
        }
    )
    # 3443：最新 5 筆 SUM 皆為負 → 不計入
    for d in dates:
        rows.append(
            {"ticker": "3443", "date": d, "foreign_net": -10, "trust_net": -10}
        )
    _add_flows(client, rows)

    chip = client.get(f"/api/topics/{SLUG}").json()["chip_signals"]
    assert chip["window_days"] == 5
    assert chip["total"] == 17  # distinct members
    assert chip["foreign_buy"] == 1  # 只有 2330
    assert chip["trust_buy"] == 1
    assert chip["major_buy"] is None
    # updated_at＝flows 最大 date，帶 Z 尾碼
    assert chip["updated_at"] == f"{_d(1)}T00:00:00Z"


def test_chip_signals_all_zero_when_no_flows(client):
    _seed_real(client)
    chip = client.get(f"/api/topics/{SLUG}").json()["chip_signals"]
    assert chip["total"] == 17
    assert chip["foreign_buy"] == 0
    assert chip["trust_buy"] == 0
    assert chip["major_buy"] is None
    assert chip["updated_at"] is None


# ── case 6: 未知 slug → 404 統一錯誤格式 ──────────────────────────────────
def test_unknown_slug_returns_404(client):
    _seed_real(client)
    r = client.get("/api/topics/does-not-exist")
    assert r.status_code == 404
    assert r.json() == {
        "error": {"code": "not_found", "message": "找不到此題材"}
    }


# ── case 7: 無任何 quotes → 三陣列每檔 change_pct 全 null（成員仍列出）不炸 ──
def test_treemap_all_null_when_no_quotes(client):
    _seed_real(client)
    tm = client.get(f"/api/topics/{SLUG}").json()["treemap"]
    for period in ("day", "week", "month"):
        assert len(tm[period]) == 17  # 全部成員列出
        assert all(i["change_pct"] is None for i in tm[period])
        assert all(i["name"] for i in tm[period])  # 名稱仍帶出


# ── case 8: quotes_updated_at 取 fetch_tw_quotes 最新成功 run，帶 Z；無 run → null
def test_quotes_updated_at_from_fetch_tw_quotes_success(client):
    _seed_real(client)
    finished = datetime(2026, 7, 11, 6, 5, 12)
    # 較舊的成功、較新的失敗：quotes_updated_at 應取最新「成功」run 的 finished_at
    _add_run(
        client,
        job_name="fetch_tw_quotes",
        status="success",
        started_at=finished,
        finished_at=finished,
    )
    _add_run(
        client,
        job_name="fetch_tw_quotes",
        status="failed",
        started_at=datetime(2026, 7, 12, 6, 5, 0),
        finished_at=datetime(2026, 7, 12, 6, 5, 5),
    )
    body = client.get(f"/api/topics/{SLUG}").json()
    assert body["quotes_updated_at"] == "2026-07-11T06:05:12Z"


def test_quotes_updated_at_null_when_no_run(client):
    _seed_real(client)
    assert client.get(f"/api/topics/{SLUG}").json()["quotes_updated_at"] is None


# ── 查詢時間下界：過舊資料不進入計算（避免無界掃描的行為驗證）──────────────
def test_quotes_older_than_lookback_are_excluded(client):
    _seed_real(client)
    # 唯一一筆 quote 在 70 日曆日前（> 60 日下界）→ 視同無 quotes，day 為 null
    _add_quotes(
        client,
        [{"ticker": "2330", "date": _d(70), "close": 100.0, "change_pct": 5.0}],
    )
    tm = client.get(f"/api/topics/{SLUG}").json()["treemap"]
    assert _item(tm["day"], "2330")["change_pct"] is None


def test_flows_older_than_lookback_are_excluded(client):
    _seed_real(client)
    # 唯一一筆 flow 在 30 日曆日前（> 21 日下界）→ 視同無 flows
    _add_flows(
        client,
        [{"ticker": "2330", "date": _d(30), "foreign_net": 999, "trust_net": 999}],
    )
    chip = client.get(f"/api/topics/{SLUG}").json()["chip_signals"]
    assert chip["foreign_buy"] == 0
    assert chip["trust_buy"] == 0
    assert chip["updated_at"] is None
