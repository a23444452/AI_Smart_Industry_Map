"""Tests for the companies API — list、detail、charts 三端點與分位數單元測試.

`client` fixture 跑真實 lifespan 對 per-test tmp DB，engine 掛在
`app.state.engine`；測試以真實 seeds（load_seeds）建 17 檔題材成員，再手插已知
quotes / per_daily / fundamentals / major_holders / institutional_flows，
API 讀到的就是測試寫入的。分位數計算另有純函式單元測試（手算對照）。
"""

from datetime import timedelta

from sqlalchemy.orm import Session

from app.api.companies import _quantile
from app.core.config import settings
from app.db import models
from app.db.base import utcnow
from app.db.seed import load_seeds

SP = "silicon-photonics"


def _d(days_ago: int) -> str:
    return (utcnow().date() - timedelta(days=days_ago)).isoformat()


def _engine(client):
    return client.app.state.engine


def _seed_real(client) -> None:
    with Session(_engine(client)) as s:
        load_seeds(settings.seeds_dir, s)
        s.commit()


def _add(client, rows: list) -> None:
    with Session(_engine(client)) as s:
        for r in rows:
            s.add(r)
        s.commit()


def _q(**kw):
    return models.QuoteDaily(**kw)


def _per(**kw):
    return models.PerDaily(**kw)


def _fund(**kw):
    return models.Fundamental(**kw)


def _hold(**kw):
    return models.MajorHolder(**kw)


def _flow(**kw):
    return models.InstitutionalFlow(**kw)


def _list(client, **params) -> dict:
    r = client.get("/api/companies", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def _item(body: dict, ticker: str) -> dict:
    return next(it for it in body["items"] if it["ticker"] == ticker)


# ── 清單：頂層結構與欄位 ─────────────────────────────────────────────────
def test_list_default_shape(client):
    _seed_real(client)
    body = _list(client)
    assert set(body.keys()) == {
        "total",
        "page",
        "page_size",
        "items",
        "topics_facets",
    }
    assert body["total"] == 17
    assert body["page"] == 1
    assert body["page_size"] == 20
    assert len(body["items"]) == 17
    item = body["items"][0]
    assert set(item.keys()) == {
        "ticker",
        "name",
        "market",
        "topics",
        "close",
        "change_pct",
        "per",
        "revenue_yoy",
    }
    # topics 為 slug 清單
    assert item["topics"] == [SP]
    # topics_facets 為全部 topics（下拉用）
    assert {f["slug"] for f in body["topics_facets"]} == {SP}
    assert set(body["topics_facets"][0].keys()) == {"slug", "title"}


def test_list_items_sorted_by_ticker_asc(client):
    _seed_real(client)
    body = _list(client)
    tickers = [it["ticker"] for it in body["items"]]
    assert tickers == sorted(tickers)


# ── 清單：query 比對 ticker 前綴 OR name 包含 ────────────────────────────
def test_list_query_ticker_prefix(client):
    _seed_real(client)
    body = _list(client, query="24")
    # 2489、2426 前綴符合；名稱不含 "24"
    assert {it["ticker"] for it in body["items"]} == {"2489", "2426"}
    assert body["total"] == 2


def test_list_query_name_contains(client):
    _seed_real(client)
    body = _list(client, query="華星")
    assert {it["ticker"] for it in body["items"]} == {"4979"}


# ── 清單：topic 篩選（distinct）＋ facets 恆為全部 ────────────────────────
def test_list_topic_filter_and_facets_all(client):
    _seed_real(client)
    # 加一檔只屬於另一新題材的公司
    with Session(_engine(client)) as s:
        s.add(models.Topic(slug="other", title="其他題材", market_tab="tw"))
        s.add(models.Company(ticker="9999", name="外星科技", market="TW"))
        s.flush()
        s.add(
            models.TopicCompany(
                topic_slug="other", ticker="9999", category="X", chain_level="上游"
            )
        )
        s.commit()

    # 不篩選 → 18 檔，facets 兩個題材
    allb = _list(client)
    assert allb["total"] == 18
    assert {f["slug"] for f in allb["topics_facets"]} == {SP, "other"}

    # 篩 silicon-photonics → 仍 17，facets 依然全部（下拉用）
    spb = _list(client, topic=SP)
    assert spb["total"] == 17
    assert "9999" not in {it["ticker"] for it in spb["items"]}
    assert {f["slug"] for f in spb["topics_facets"]} == {SP, "other"}

    # 篩 other → 只 9999
    ob = _list(client, topic="other")
    assert ob["total"] == 1
    assert ob["items"][0]["ticker"] == "9999"


def test_list_topic_filter_distinct_no_dup(client):
    """同 ticker 跨多分類，topic 篩選後只出現一次。"""
    _seed_real(client)
    body = _list(client, topic=SP)
    tickers = [it["ticker"] for it in body["items"]]
    assert len(tickers) == len(set(tickers))
    assert body["total"] == len(tickers)


# ── 清單：分頁 ──────────────────────────────────────────────────────────
def test_list_pagination(client):
    _seed_real(client)
    p1 = _list(client, page=1, page_size=5)
    assert p1["total"] == 17
    assert p1["page_size"] == 5
    assert len(p1["items"]) == 5
    p2 = _list(client, page=2, page_size=5)
    assert len(p2["items"]) == 5
    p4 = _list(client, page=4, page_size=5)
    assert len(p4["items"]) == 2  # 17 = 5+5+5+2
    # 跨頁 ticker 升冪且不重疊
    seen = (
        [it["ticker"] for it in p1["items"]]
        + [it["ticker"] for it in p2["items"]]
        + [it["ticker"] for it in p4["items"]]
    )
    got_p3 = _list(client, page=3, page_size=5)
    seen = (
        [it["ticker"] for it in p1["items"]]
        + [it["ticker"] for it in p2["items"]]
        + [it["ticker"] for it in got_p3["items"]]
        + [it["ticker"] for it in p4["items"]]
    )
    assert seen == sorted(seen)
    assert len(set(seen)) == 17


def test_list_page_size_over_100_returns_422(client):
    _seed_real(client)
    r = client.get("/api/companies", params={"page_size": 101})
    assert r.status_code == 422


def test_list_page_zero_returns_422(client):
    _seed_real(client)
    r = client.get("/api/companies", params={"page": 0})
    assert r.status_code == 422


def test_list_page_size_zero_returns_422(client):
    _seed_real(client)
    r = client.get("/api/companies", params={"page_size": 0})
    assert r.status_code == 422


# ── 清單：各表最新值（nullable）───────────────────────────────────────────
def test_list_latest_values_pick_newest_row(client):
    _seed_real(client)
    _add(
        client,
        [
            _q(ticker="2330", date=_d(3), close=100.0, change_pct=1.0),
            _q(ticker="2330", date=_d(0), close=2415.0, change_pct=-2.0),
            _per(ticker="2330", date=_d(3), per=10.0),
            _per(ticker="2330", date=_d(0), per=22.5),
            _fund(ticker="2330", month="2026-05", revenue=100, yoy=5.0),
            _fund(ticker="2330", month="2026-06", revenue=200, yoy=33.3),
        ],
    )
    body = _list(client)
    it = _item(body, "2330")
    assert it["close"] == 2415.0
    assert it["change_pct"] == -2.0
    assert it["per"] == 22.5
    assert it["revenue_yoy"] == 33.3


def test_list_missing_values_are_null(client):
    _seed_real(client)
    it = _item(_list(client), "6789")
    assert it["close"] is None
    assert it["change_pct"] is None
    assert it["per"] is None
    assert it["revenue_yoy"] is None


# ── 詳情 ────────────────────────────────────────────────────────────────
def _detail(client, ticker: str):
    return client.get(f"/api/companies/{ticker}")


def test_detail_shape_and_fields(client):
    _seed_real(client)
    _add(
        client,
        [
            _q(
                ticker="2330",
                date=_d(1),
                close=2400.0,
                change_pct=1.0,
                volume=10,
            ),
            _q(
                ticker="2330",
                date=_d(0),
                open=2410.0,
                high=2420.0,
                low=2400.0,
                close=2415.0,
                change_pct=0.63,
                volume=12345,
            ),
            _per(ticker="2330", date=_d(0), per=22.5, pbr=6.1, dividend_yield=1.8),
            _fund(ticker="2330", month="2026-06", revenue=200, yoy=33.3),
            _hold(ticker="2330", week=_d(0), ratio_400up=77.7),
        ],
    )
    r = _detail(client, "2330")
    assert r.status_code == 200
    b = r.json()
    assert set(b.keys()) == {
        "ticker",
        "name",
        "market",
        "close",
        "change",
        "change_pct",
        "volume",
        "topics",
        "badges",
        "per",
        "pbr",
        "dividend_yield",
        "latest_revenue",
        "major_holder",
        "quotes_updated_at",
    }
    assert b["ticker"] == "2330"
    assert b["name"] == "台積電"
    assert b["market"] == "TW"
    assert b["close"] == 2415.0
    assert b["change_pct"] == 0.63
    assert b["volume"] == 12345
    assert b["per"] == 22.5
    assert b["pbr"] == 6.1
    assert b["dividend_yield"] == 1.8
    assert b["latest_revenue"] == {"month": "2026-06", "revenue": 200, "yoy": 33.3}
    assert b["major_holder"] == {"week": _d(0), "ratio_400up": 77.7}
    # topics 為物件 {slug,title}
    assert b["topics"] == [{"slug": SP, "title": "光通訊｜矽光子與 CPO"}]


def test_detail_change_computed_from_two_quotes(client):
    _seed_real(client)
    _add(
        client,
        [
            _q(ticker="3443", date=_d(1), close=1000.0),
            _q(ticker="3443", date=_d(0), close=1023.5),
        ],
    )
    b = _detail(client, "3443").json()
    assert b["change"] == 23.5


def test_detail_change_null_when_insufficient(client):
    _seed_real(client)
    _add(client, [_q(ticker="3443", date=_d(0), close=1000.0)])
    b = _detail(client, "3443").json()
    assert b["change"] is None
    assert b["close"] == 1000.0


def test_detail_badges_reuse_topic_map_logic(client):
    _seed_real(client)
    _add(
        client,
        [
            # 2330 has_futures；最新一筆外資賣、投信買
            _flow(ticker="2330", date=_d(2), foreign_net=999, trust_net=-1),
            _flow(ticker="2330", date=_d(0), foreign_net=-10, trust_net=20),
        ],
    )
    b = _detail(client, "2330").json()
    assert b["badges"] == ["有股票期貨", "投信買超"]
    # 3450 無 futures、無 flows → 空
    assert _detail(client, "3450").json()["badges"] == []


def test_detail_latest_revenue_and_holder_null(client):
    _seed_real(client)
    b = _detail(client, "3163").json()
    assert b["latest_revenue"] is None
    assert b["major_holder"] is None


def test_detail_quotes_updated_at_from_pipeline_run(client):
    _seed_real(client)
    with Session(_engine(client)) as s:
        s.add(
            models.PipelineRun(
                job_name="fetch_tw_quotes",
                status="success",
                finished_at=utcnow(),
            )
        )
        s.commit()
    b = _detail(client, "2330").json()
    assert b["quotes_updated_at"] is not None
    assert b["quotes_updated_at"].endswith("Z")


def test_detail_unknown_ticker_404(client):
    _seed_real(client)
    r = _detail(client, "0000")
    assert r.status_code == 404
    assert r.json() == {
        "error": {"code": "not_found", "message": "找不到此公司"}
    }


# ── 圖表 ────────────────────────────────────────────────────────────────
def _chart(client, ticker: str, kind: str):
    return client.get(f"/api/companies/{ticker}/charts/{kind}")


def test_chart_kline_ascending(client):
    _seed_real(client)
    _add(
        client,
        [
            _q(
                ticker="2330",
                date=_d(0),
                open=1,
                high=2,
                low=0.5,
                close=1.5,
                volume=9,
            ),
            _q(
                ticker="2330",
                date=_d(2),
                open=3,
                high=4,
                low=2.5,
                close=3.5,
                volume=7,
            ),
        ],
    )
    r = _chart(client, "2330", "kline")
    assert r.status_code == 200
    items = r.json()["items"]
    assert [it["date"] for it in items] == [_d(2), _d(0)]  # 升冪
    assert set(items[0].keys()) == {
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
    }
    assert items[0]["open"] == 3


def test_chart_institutional_last_60_ascending(client):
    _seed_real(client)
    rows = [
        _flow(ticker="2330", date=_d(i), foreign_net=i, trust_net=-i, dealer_net=1)
        for i in range(70)
    ]
    _add(client, rows)
    items = _chart(client, "2330", "institutional").json()["items"]
    assert len(items) == 60  # 只近 60
    dates = [it["date"] for it in items]
    assert dates == sorted(dates)  # 升冪
    assert set(items[0].keys()) == {
        "date",
        "foreign_net",
        "trust_net",
        "dealer_net",
    }
    # 近 60 應涵蓋 _d(0)（最新），不含 _d(69)（最舊被截）
    assert _d(0) in dates
    assert _d(69) not in dates


def test_chart_holders_ascending(client):
    _seed_real(client)
    _add(
        client,
        [
            _hold(ticker="2330", week=_d(0), ratio_400up=80.0),
            _hold(ticker="2330", week=_d(7), ratio_400up=79.0),
        ],
    )
    items = _chart(client, "2330", "holders").json()["items"]
    assert [it["week"] for it in items] == [_d(7), _d(0)]
    assert set(items[0].keys()) == {"week", "ratio_400up"}


def test_chart_per_river_bands(client):
    _seed_real(client)
    # 12 個 PER 值（>=10）→ 有分位；close 取 quotes 同日
    per_rows = []
    quote_rows = []
    pers = [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21]
    for i, p in enumerate(pers):
        day = _d(30 - i)
        per_rows.append(_per(ticker="2330", date=day, per=float(p)))
        quote_rows.append(_q(ticker="2330", date=day, close=float(p) * 5.0))
    _add(client, per_rows + quote_rows)
    items = _chart(client, "2330", "per_river").json()["items"]
    assert len(items) == 12
    dates = [it["date"] for it in items]
    assert dates == sorted(dates)
    first = items[0]
    assert set(first.keys()) == {
        "date",
        "close",
        "band_p10",
        "band_p25",
        "band_p50",
        "band_p75",
        "band_p90",
    }
    # close 來自 quotes 同日
    assert first["close"] == pers[0] * 5.0  # 對應最舊日 _d(30) per=10 close=50
    # EPS_ttm = close/PER = 50/10 = 5；band_p50 = 5 * P50(pers)
    p50 = _quantile(sorted(float(p) for p in pers), 0.50)
    assert first["band_p50"] == round(5.0 * p50, 2)
    # 所有 band 非 null
    for k in ("band_p10", "band_p25", "band_p50", "band_p75", "band_p90"):
        assert first[k] is not None


def test_chart_per_river_below_10_samples_all_null(client):
    _seed_real(client)
    per_rows = []
    quote_rows = []
    for i in range(9):  # <10 → 全 null band
        day = _d(20 - i)
        per_rows.append(_per(ticker="2330", date=day, per=float(10 + i)))
        quote_rows.append(_q(ticker="2330", date=day, close=100.0))
    _add(client, per_rows + quote_rows)
    items = _chart(client, "2330", "per_river").json()["items"]
    assert len(items) == 9
    for it in items:
        for k in ("band_p10", "band_p25", "band_p50", "band_p75", "band_p90"):
            assert it[k] is None
        assert it["close"] == 100.0


def test_chart_per_river_zero_or_none_per_day_bands_null(client):
    _seed_real(client)
    # 12 有效樣本供分位；再插一日 PER=0 與一日 close 缺
    per_rows = []
    quote_rows = []
    for i in range(12):
        day = _d(40 - i)
        per_rows.append(_per(ticker="2330", date=day, per=float(10 + i)))
        quote_rows.append(_q(ticker="2330", date=day, close=200.0))
    # PER=0 當日 → band 全 null（且不列入分位樣本）
    per_rows.append(_per(ticker="2330", date=_d(5), per=0.0))
    quote_rows.append(_q(ticker="2330", date=_d(5), close=200.0))
    # PER 有值但 quotes 缺 close（該日無 quote）→ close null、band null
    per_rows.append(_per(ticker="2330", date=_d(4), per=15.0))
    _add(client, per_rows + quote_rows)
    items = _chart(client, "2330", "per_river").json()["items"]
    by_date = {it["date"]: it for it in items}
    zero_day = by_date[_d(5)]
    for k in ("band_p10", "band_p50", "band_p90"):
        assert zero_day[k] is None
    no_close_day = by_date[_d(4)]
    assert no_close_day["close"] is None
    for k in ("band_p10", "band_p50", "band_p90"):
        assert no_close_day[k] is None


def test_chart_unknown_kind_422(client):
    _seed_real(client)
    r = _chart(client, "2330", "bogus")
    assert r.status_code == 422


def test_chart_unknown_ticker_404(client):
    _seed_real(client)
    r = _chart(client, "0000", "kline")
    assert r.status_code == 404
    assert r.json() == {
        "error": {"code": "not_found", "message": "找不到此公司"}
    }


def test_chart_ticker_without_data_empty_items(client):
    _seed_real(client)
    for kind in ("kline", "per_river", "institutional", "holders"):
        r = _chart(client, "6789", kind)
        assert r.status_code == 200
        assert r.json()["items"] == []


# ── 分位數純函式單元測試（手算對照，R-7 線性插值）──────────────────────────
def test_quantile_known_20_samples():
    # 已知 20 筆：1..20（已排序）。R-7 線性插值：pos = q*(n-1) = q*19。
    data = [float(i) for i in range(1, 21)]
    # P10：pos = 0.10*19 = 1.9 → data[1] + 0.9*(data[2]-data[1]) = 2 + 0.9*1 = 2.9
    assert round(_quantile(data, 0.10), 10) == 2.9
    # P50：pos = 0.50*19 = 9.5 → data[9] + 0.5*(data[10]-data[9]) = 10 + 0.5 = 10.5
    assert _quantile(data, 0.50) == 10.5
    # P90：pos = 0.90*19 = 17.1 → data[17] + 0.1*(data[18]-data[17]) = 18 + 0.1 = 18.1
    assert round(_quantile(data, 0.90), 10) == 18.1


def test_quantile_single_value():
    assert _quantile([42.0], 0.5) == 42.0


def test_quantile_endpoints():
    data = [5.0, 10.0, 15.0, 20.0]
    assert _quantile(data, 0.0) == 5.0
    assert _quantile(data, 1.0) == 20.0
