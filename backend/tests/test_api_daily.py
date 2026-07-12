"""Tests for GET /api/daily 與 GET /api/daily/announcements（每日焦點頁資料）.

`client` fixture 跑真實 lifespan 對 per-test tmp DB，engine 掛在
`app.state.engine`；測試透過同一 engine 手插已知資料，API 讀到的就是測試寫入的。

日期策略：indices／market_flows／margin／announcements 無查詢時間下界，用固定日期；
movers 走 ``quotes_by_ticker``（60 日曆日下界），故 quotes 用相對「今日」日期，避免
固定日期隨真實時間流逝掉出視窗。
"""

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.db import models
from app.db.base import _utcnow


def _engine(client):
    return client.app.state.engine


def _d(days_ago: int) -> str:
    """今日（UTC）往回 ``days_ago`` 日曆日的 ISO 日期（quotes 相對日期用）。"""
    return (_utcnow().date() - timedelta(days=days_ago)).isoformat()


def _add(client, rows: list) -> None:
    with Session(_engine(client)) as s:
        for r in rows:
            s.add(r)
        s.commit()


def _mover(items: list[dict], ticker: str) -> dict | None:
    return next((i for i in items if i["ticker"] == ticker), None)


# ── GET /api/daily：空 DB 不炸 ────────────────────────────────────────────
def test_daily_all_empty_does_not_crash(client):
    r = client.get("/api/daily")
    assert r.status_code == 200
    body = r.json()
    assert body["indices"] == []
    assert body["market_flows"] == {"date": None, "rows": []}
    assert body["margin"] == {"date": None, "rows": []}
    assert body["movers"] == {"day": [], "week": [], "month": []}
    assert body["announcements_dates"] == []


# ── indices：依 SYMBOLS 定義順序、欄位齊全、fetched_at 帶 Z（null 亦可） ────
def test_daily_indices_ordered_by_symbols_definition(client):
    fetched = datetime(2026, 7, 11, 13, 30, 0)
    # 故意以「非 SYMBOLS 順序」插入，驗證輸出仍照定義順序（^TWII 先於 ^SOX）
    _add(
        client,
        [
            models.IndexSnapshot(
                symbol="^SOX",
                name="費城半導體",
                price=5000.0,
                change=-12.5,
                change_pct=-0.25,
                fetched_at=fetched,
            ),
            models.IndexSnapshot(
                symbol="^TWII",
                name="加權指數",
                price=23000.0,
                change=100.0,
                change_pct=0.44,
                fetched_at=None,  # fetched_at 可為 null
            ),
        ],
    )
    indices = client.get("/api/daily").json()["indices"]
    assert [i["symbol"] for i in indices] == ["^TWII", "^SOX"]
    twii = indices[0]
    assert set(twii.keys()) == {
        "symbol",
        "name",
        "price",
        "change",
        "change_pct",
        "fetched_at",
    }
    assert twii["fetched_at"] is None
    assert indices[1]["fetched_at"] == "2026-07-11T13:30:00Z"


# ── market_flows / margin：取最新一日的列，原名原樣輸出 ───────────────────
def test_daily_flows_and_margin_latest_date_rows(client):
    _add(
        client,
        [
            # 兩個日期；API 應只回最新日（2026-07-11）的列
            models.MarketFlow(
                date="2026-07-10", unit="合計", buy=1, sell=2, net=-1
            ),
            models.MarketFlow(
                date="2026-07-11",
                unit="外資及陸資(不含外資自營商)",
                buy=1000,
                sell=800,
                net=200,
            ),
            models.MarketFlow(
                date="2026-07-11", unit="投信", buy=500, sell=None, net=None
            ),
            models.MarginBalance(
                date="2026-07-09",
                item="融資(交易單位)",
                buy=1,
                sell=1,
                prev_balance=1,
                today_balance=1,
            ),
            models.MarginBalance(
                date="2026-07-11",
                item="融資(交易單位)",
                buy=100,
                sell=50,
                prev_balance=1000,
                today_balance=1050,
            ),
        ],
    )
    body = client.get("/api/daily").json()

    flows = body["market_flows"]
    assert flows["date"] == "2026-07-11"
    units = {row["unit"] for row in flows["rows"]}
    assert units == {"外資及陸資(不含外資自營商)", "投信"}
    trust = next(r for r in flows["rows"] if r["unit"] == "投信")
    assert trust["sell"] is None and trust["net"] is None

    margin = body["margin"]
    assert margin["date"] == "2026-07-11"
    assert len(margin["rows"]) == 1
    assert margin["rows"][0]["item"] == "融資(交易單位)"
    assert margin["rows"][0]["today_balance"] == 1050


# ── movers：day 取最新 change_pct、week/month 走 5/21 offset；降冪 top、null 排除
def test_daily_movers_periods_sort_and_null_exclusion(client):
    # 2330：22 日 close（最新 121 往回每日 -1）→ week=(121/116-1)*100=4.31、
    #       month=(121/100-1)*100=21.0；最新日 change_pct=5.0
    rows = [
        models.Company(ticker="2330", name="台積電", market="TW"),
        models.Company(ticker="3443", name="創意", market="TW"),
        models.Company(ticker="6415", name="矽力", market="TW"),
    ]
    closes = [121.0 - i for i in range(22)]
    for i, close in enumerate(closes):
        row = models.QuoteDaily(ticker="2330", date=_d(i), close=close)
        if i == 0:
            row.change_pct = 5.0
        rows.append(row)
    # 3443：3 日 → week/month 不足 → 該檔不進 week/month 榜；day 有值 -2.0
    for i, close in enumerate([50.0, 49.0, 48.0]):
        row = models.QuoteDaily(ticker="3443", date=_d(i), close=close)
        if i == 0:
            row.change_pct = -2.0
        rows.append(row)
    # 6415：最新日 change_pct=null → 不進 day 榜（null 排除）
    rows.append(models.QuoteDaily(ticker="6415", date=_d(0), close=10.0, change_pct=None))
    _add(client, rows)

    movers = client.get("/api/daily").json()["movers"]

    # day：2330(5.0) 在 3443(-2.0) 之前（降冪）；6415（null）不在列
    day_tickers = [m["ticker"] for m in movers["day"]]
    assert day_tickers == ["2330", "3443"]
    assert _mover(movers["day"], "6415") is None
    d2330 = _mover(movers["day"], "2330")
    assert d2330["change_pct"] == 5.0
    assert d2330["close"] == 121.0
    assert d2330["name"] == "台積電"  # name 來自 companies

    # week/month：只有 2330 足天數
    assert [m["ticker"] for m in movers["week"]] == ["2330"]
    assert _mover(movers["week"], "2330")["change_pct"] == 4.31
    assert [m["ticker"] for m in movers["month"]] == ["2330"]
    assert _mover(movers["month"], "2330")["change_pct"] == 21.0


# ── movers name 來自 companies；quotes-only ticker（不在 companies）→ name 退回 ticker
def test_daily_movers_name_from_companies_with_fallback(client):
    _add(
        client,
        [
            models.Company(ticker="2330", name="台積電", market="TW"),
            models.QuoteDaily(ticker="2330", date=_d(0), close=100.0, change_pct=1.0),
            # 9999 無對應 company → name 退回 ticker，不得為 null
            models.QuoteDaily(ticker="9999", date=_d(0), close=50.0, change_pct=2.0),
        ],
    )
    day = client.get("/api/daily").json()["movers"]["day"]
    assert _mover(day, "2330")["name"] == "台積電"
    assert _mover(day, "9999")["name"] == "9999"


# ── announcements_dates：published_at 轉台北日期、distinct 降冪取 7 ─────────
def test_daily_announcements_dates_taipei_distinct_desc(client):
    # UTC 15:30 → 台北 23:30 同日；UTC 16:30 → 台北隔日 00:30。驗證跨日換算與去重。
    _add(
        client,
        [
            _ann(datetime(2026, 7, 10, 15, 30), ticker="2330", title="a"),
            _ann(datetime(2026, 7, 10, 16, 30), ticker="2330", title="b"),  # 台北 7/11
            _ann(datetime(2026, 7, 11, 2, 0), ticker="3443", title="c"),  # 台北 7/11（去重）
        ],
    )
    dates = client.get("/api/daily").json()["announcements_dates"]
    assert dates == ["2026-07-11", "2026-07-10"]


def _ann(published_at, *, ticker, title, category="重大事件", name="某公司"):
    return models.MopsAnnouncement(
        ticker=ticker,
        name=name,
        category=category,
        title=title,
        published_at=published_at,
    )


# ── GET /api/daily/announcements?date=... ────────────────────────────────
def test_announcements_by_taipei_date_filters_and_orders(client):
    _add(
        client,
        [
            # 台北 2026-07-12 當日兩筆（UTC 7/11 16:30 與 7/12 03:00），降冪
            _ann(datetime(2026, 7, 11, 16, 30), ticker="2330", title="早", name="台積電"),
            _ann(datetime(2026, 7, 12, 3, 0), ticker="3443", title="晚", name="創意"),
            # 台北 2026-07-11（UTC 7/11 15:30）→ 不在 7/12 範圍
            _ann(datetime(2026, 7, 11, 15, 30), ticker="6415", title="前一日"),
            # 台北 2026-07-13（UTC 7/12 16:30）→ 不在 7/12 範圍
            _ann(datetime(2026, 7, 12, 16, 30), ticker="3661", title="隔日"),
            # 澄清回應 → 過濾掉，即使在當日
            _ann(
                datetime(2026, 7, 12, 5, 0),
                ticker="2330",
                title="澄清",
                category="澄清回應",
            ),
        ],
    )
    r = client.get("/api/daily/announcements?date=2026-07-12")
    assert r.status_code == 200
    items = r.json()
    assert [i["title"] for i in items] == ["晚", "早"]  # published_at 降冪
    first = items[0]
    assert set(first.keys()) == {
        "ticker",
        "name",
        "category",
        "title",
        "published_at",
    }
    assert first["ticker"] == "3443"
    assert first["name"] == "創意"
    assert first["published_at"] == "2026-07-12T03:00:00Z"  # 帶 Z


def test_announcements_missing_date_returns_422(client):
    assert client.get("/api/daily/announcements").status_code == 422


def test_announcements_malformed_date_returns_422(client):
    assert client.get("/api/daily/announcements?date=2026-13-99").status_code == 422
    assert client.get("/api/daily/announcements?date=notadate").status_code == 422


def test_announcements_empty_day_returns_empty_list(client):
    r = client.get("/api/daily/announcements?date=2026-07-12")
    assert r.status_code == 200
    assert r.json() == []
