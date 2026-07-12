"""Tests for the fetch_tw_quotes job — TWSE+TPEx close data into quotes_daily.

No network: twse.fetch / tpex.fetch are monkeypatched to return the recorded
fixtures' raw row lists. The job then parses, filters to known companies, and
upserts quotes_daily. It must obey the runner transaction contract (no
commit/rollback inside the fn) — tests drive commits explicitly.
"""

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.orm import Session

from app.db import models
from app.db.base import Base, make_engine
from app.pipeline import jobs, jobs_backfill, jobs_daily, jobs_monthly
from app.pipeline.sources import (
    _common,
    mops,
    tdcc_holders,
    tpex,
    tpex_history,
    tpex_institutional,
    tpex_per,
    tpex_revenue,
    twse,
    twse_bfi82u,
    twse_history,
    twse_margin,
    twse_per,
    twse_per_history,
    twse_revenue,
    twse_t86,
    yahoo_indices,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def _taipei_today() -> str:
    return datetime.now(ZoneInfo("Asia/Taipei")).date().isoformat()


@pytest.fixture
def twse_raw() -> list[dict]:
    return json.loads(
        (FIXTURES_DIR / "twse_stock_day_all.json").read_text(encoding="utf-8")
    )


@pytest.fixture
def tpex_raw() -> list[dict]:
    return json.loads(
        (FIXTURES_DIR / "tpex_daily_close.json").read_text(encoding="utf-8")
    )


@pytest.fixture
def eng(tmp_path):
    engine = make_engine(f"{tmp_path}/t.db")
    Base.metadata.create_all(engine)
    return engine


def _patch_sources(monkeypatch, twse_raw, tpex_raw) -> None:
    monkeypatch.setattr(twse, "fetch", lambda: twse_raw)
    monkeypatch.setattr(tpex, "fetch", lambda: tpex_raw)


def _seed_companies(session: Session, tickers: list[str]) -> None:
    for t in tickers:
        session.add(models.Company(ticker=t, name=f"名稱{t}", market="TW"))
    session.flush()


def test_fetch_upserts_quotes_for_known_companies(monkeypatch, eng, twse_raw, tpex_raw):
    _patch_sources(monkeypatch, twse_raw, tpex_raw)
    with Session(eng) as s:
        # 2330 上市、3081 上櫃在 fixtures 內；1111 不在 fixtures。
        _seed_companies(s, ["2330", "3081", "1111"])
        jobs.fetch_tw_quotes(s)
        s.commit()

    with Session(eng) as s:
        q2330 = s.get(models.QuoteDaily, ("2330", "2026-07-09"))
        q3081 = s.get(models.QuoteDaily, ("3081", "2026-07-09"))
        assert q2330 is not None
        assert q3081 is not None
        # date 以來源 ROC Date 1150709 -> 2026-07-09 為準
        assert q2330.date == "2026-07-09"
        assert q3081.date == "2026-07-09"
        # change_pct 正確（2330: Change=-50, Close=2415 -> prev 2465）
        assert q2330.change_pct == pytest.approx(-50 / 2465 * 100, abs=1e-9)
        # 3081: Change="-90.00 ", Close=2005 -> prev 2095
        assert q3081.change_pct == pytest.approx(-90 / 2095 * 100, abs=1e-9)
        assert q2330.close == 2415
        assert q3081.close == 2005


def test_only_known_tickers_are_upserted(monkeypatch, eng, twse_raw, tpex_raw):
    _patch_sources(monkeypatch, twse_raw, tpex_raw)
    with Session(eng) as s:
        _seed_companies(s, ["2330", "3081"])
        jobs.fetch_tw_quotes(s)
        s.commit()

    with Session(eng) as s:
        tickers = {q.ticker for q in s.query(models.QuoteDaily).all()}
        # fixtures 內的 ETF 代號（00400A、006201…）不在 companies，不得入庫。
        assert tickers == {"2330", "3081"}


def test_rerun_same_day_is_idempotent(monkeypatch, eng, twse_raw, tpex_raw):
    _patch_sources(monkeypatch, twse_raw, tpex_raw)
    with Session(eng) as s:
        _seed_companies(s, ["2330", "3081"])
        jobs.fetch_tw_quotes(s)
        s.commit()
    with Session(eng) as s:
        jobs.fetch_tw_quotes(s)  # 同日重跑
        s.commit()

    with Session(eng) as s:
        assert s.query(models.QuoteDaily).count() == 2  # 無重複列


def test_row_with_none_date_is_skipped(monkeypatch, eng):
    # date 為 None 的列（ROC Date 缺失/異常）跳過，不入庫。
    bad_twse = [
        {
            "Date": "",  # roc_to_iso -> None
            "Code": "2330",
            "Name": "台積電",
            "OpeningPrice": "100",
            "HighestPrice": "100",
            "LowestPrice": "100",
            "ClosingPrice": "100",
            "TradeVolume": "1",
            "Change": "0",
        }
    ]
    monkeypatch.setattr(twse, "fetch", lambda: bad_twse)
    monkeypatch.setattr(tpex, "fetch", lambda: [])
    with Session(eng) as s:
        _seed_companies(s, ["2330"])
        jobs.fetch_tw_quotes(s)
        s.commit()

    with Session(eng) as s:
        assert s.query(models.QuoteDaily).count() == 0


def test_source_fetch_error_propagates(monkeypatch, eng, tpex_raw):
    # 一個來源 fetch 失敗 → 例外往上拋給 runner（不吞）。
    def boom() -> list[dict]:
        raise _common.SourceFetchError("TWSE", "連線失敗")

    monkeypatch.setattr(twse, "fetch", boom)
    monkeypatch.setattr(tpex, "fetch", lambda: tpex_raw)
    with Session(eng) as s:
        _seed_companies(s, ["2330", "3081"])
        with pytest.raises(_common.SourceFetchError):
            jobs.fetch_tw_quotes(s)


# --------------------------------------------------------------------------- #
# fetch_institutional — TWSE T86 + TPEx dailyTrade into institutional_flows
# --------------------------------------------------------------------------- #


def _patch_institutional_sources(monkeypatch, t86_raw, tpex_raw) -> None:
    # fetch(date_iso) 被 monkeypatch，回錄製的 raw dict；parse 為真、date 以呼叫端
    # 傳入的「台北今日」為準（收盤後執行，當日資料已出）。
    monkeypatch.setattr(twse_t86, "fetch", lambda date: t86_raw)
    monkeypatch.setattr(tpex_institutional, "fetch", lambda date: tpex_raw)


def test_fetch_institutional_upserts_known_tickers(monkeypatch, eng):
    t86_raw = _load("twse_t86.json")
    tpex_raw = _load("tpex_institutional.json")
    _patch_institutional_sources(monkeypatch, t86_raw, tpex_raw)
    today = _taipei_today()

    with Session(eng) as s:
        # 2330 在 T86、3081 在 TPEx；其餘 fixtures 代號未 seed，應被過濾。
        _seed_companies(s, ["2330", "3081"])
        jobs.fetch_institutional(s)
        s.commit()

    with Session(eng) as s:
        f2330 = s.get(models.InstitutionalFlow, ("2330", today))
        f3081 = s.get(models.InstitutionalFlow, ("3081", today))
        assert f2330 is not None
        assert f3081 is not None
        # 2330: 外陸資 -12,748,541 + 外資自營商 0 = -12748541
        assert f2330.foreign_net == -12_748_541
        assert f2330.trust_net == 43_225
        assert f2330.dealer_net == 89_863
        # 3081: 外資合計 idx10 -453,275 / 投信 idx13 84,000 / 自營合計 idx22 191
        assert f3081.foreign_net == -453_275
        assert f3081.trust_net == 84_000
        assert f3081.dealer_net == 191
        # 只有已知 ticker 入庫（fixtures 內 2409/00679B 等未 seed）
        tickers = {f.ticker for f in s.query(models.InstitutionalFlow).all()}
        assert tickers == {"2330", "3081"}


def test_fetch_institutional_is_idempotent(monkeypatch, eng):
    _patch_institutional_sources(
        monkeypatch, _load("twse_t86.json"), _load("tpex_institutional.json")
    )
    with Session(eng) as s:
        _seed_companies(s, ["2330", "3081"])
        jobs.fetch_institutional(s)
        s.commit()
    with Session(eng) as s:
        jobs.fetch_institutional(s)  # 同日重跑
        s.commit()
    with Session(eng) as s:
        assert s.query(models.InstitutionalFlow).count() == 2


def test_fetch_institutional_source_error_propagates(monkeypatch, eng):
    def boom(date: str) -> dict:
        raise _common.SourceFetchError("TWSE-T86", "連線失敗")

    monkeypatch.setattr(twse_t86, "fetch", boom)
    monkeypatch.setattr(
        tpex_institutional, "fetch", lambda date: _load("tpex_institutional.json")
    )
    with Session(eng) as s:
        _seed_companies(s, ["2330", "3081"])
        with pytest.raises(_common.SourceFetchError):
            jobs.fetch_institutional(s)


# --------------------------------------------------------------------------- #
# backfill_quotes — per-stock monthly history into quotes_daily
# --------------------------------------------------------------------------- #


def test_backfill_quotes_writes_history_from_both_sources(monkeypatch, eng):
    twse_hist = _load("twse_history.json")  # 2330, 21 交易日 (2026-06)
    tpex_hist = _load("tpex_history.json")  # 3081, 21 交易日 (2026-06)
    nodata = _load("twse_history_nodata.json")

    # twse 有 2330；tpex 有 3081；各自對另一檔回空，觸發 fallback 分支。
    monkeypatch.setattr(
        twse_history,
        "fetch",
        lambda ticker, year, month: twse_hist if ticker == "2330" else nodata,
    )
    monkeypatch.setattr(
        tpex_history,
        "fetch",
        lambda ticker, year, month: tpex_hist if ticker == "3081" else nodata,
    )

    with Session(eng) as s:
        _seed_companies(s, ["2330", "3081"])
        written = jobs_backfill.backfill_quotes(s, days=35)
        s.commit()

    with Session(eng) as s:
        assert s.query(models.QuoteDaily).filter_by(ticker="2330").count() == 21
        assert s.query(models.QuoteDaily).filter_by(ticker="3081").count() == 21
        # 回傳寫入筆數 = 21 + 21
        assert written == 42
        q = s.get(models.QuoteDaily, ("2330", "2026-06-30"))
        assert q is not None
        assert q.close == 2410.0
        assert q.change_pct is None  # 歷史來源 change_pct 恆為 None


def test_backfill_quotes_does_not_overwrite_existing_row(monkeypatch, eng):
    twse_hist = _load("twse_history.json")
    nodata = _load("twse_history_nodata.json")
    monkeypatch.setattr(
        twse_history,
        "fetch",
        lambda ticker, year, month: twse_hist if ticker == "2330" else nodata,
    )
    monkeypatch.setattr(tpex_history, "fetch", lambda ticker, year, month: nodata)

    with Session(eng) as s:
        _seed_companies(s, ["2330"])
        # 既有列帶 change_pct，backfill 的 None 不可蓋掉。
        s.add(
            models.QuoteDaily(
                ticker="2330", date="2026-06-30", close=999.0, change_pct=1.23
            )
        )
        s.flush()
        jobs_backfill.backfill_quotes(s, days=35)
        s.commit()

    with Session(eng) as s:
        q = s.get(models.QuoteDaily, ("2330", "2026-06-30"))
        assert q.change_pct == 1.23  # 未被 None 覆蓋
        assert q.close == 999.0  # 既有值保留
        # 其餘日期照常寫入（該月共 21 交易日）
        assert s.query(models.QuoteDaily).filter_by(ticker="2330").count() == 21


def test_backfill_quotes_skips_failing_ticker(monkeypatch, eng):
    twse_hist = _load("twse_history.json")
    nodata = _load("twse_history_nodata.json")

    def flaky_twse(ticker: str, year: int, month: int) -> dict:
        if ticker == "9999":
            raise _common.SourceFetchError("TWSE-History", "連線失敗")
        return twse_hist if ticker == "2330" else nodata

    monkeypatch.setattr(twse_history, "fetch", flaky_twse)
    monkeypatch.setattr(tpex_history, "fetch", lambda ticker, year, month: nodata)

    with Session(eng) as s:
        _seed_companies(s, ["9999", "2330"])
        written = jobs_backfill.backfill_quotes(s, days=35)  # 不因 9999 中止
        s.commit()

    with Session(eng) as s:
        # 壞掉的 9999 無列；正常的 2330 完整寫入。
        assert s.query(models.QuoteDaily).filter_by(ticker="9999").count() == 0
        assert s.query(models.QuoteDaily).filter_by(ticker="2330").count() == 21
        assert written == 21


def _make_twse_history_raw(year: int, month: int, n_days: int) -> dict:
    """合成一個 (year, month) 的 TWSE STOCK_DAY raw，含 1..n_days 日各一列。"""
    return {
        "stat": "OK",
        "date": f"{year:04d}{month:02d}01",
        "title": f"{year - 1911}年{month:02d}月 測試",
        "fields": [
            "日期", "成交股數", "成交金額", "開盤價", "最高價",
            "最低價", "收盤價", "漲跌價差", "成交筆數", "註記",
        ],
        "data": [
            [
                f"{year - 1911}/{month:02d}/{day:02d}",
                "1,000", "10,500", "10.00", "11.00", "9.00", "10.50",
                "+0.10", "5", "",
            ]
            for day in range(1, n_days + 1)
        ],
    }


def _recent_months(n: int) -> list[tuple[int, int]]:
    """由當月起往回 n 個月的 (year, month) 列表（新到舊）。"""
    today = datetime.now(ZoneInfo("Asia/Taipei")).date()
    months = [(today.year, today.month)]
    for _ in range(n - 1):
        months.append(jobs_backfill._prev_month(*months[-1]))
    return months


def test_collect_history_accumulates_across_months(monkeypatch):
    # 當月只有 3 筆、前兩個月各 21 筆 → 3+21=24 < 35 要再走第三個月，
    # 45 ≥ 35 才停：驗證跨月累加、月序（新到舊）與日期正確性。
    m0, m1, m2 = _recent_months(3)
    days_by_month = {m0: 3, m1: 21, m2: 21}
    calls: list[tuple[int, int]] = []

    def fake_twse(ticker: str, year: int, month: int) -> dict:
        calls.append((year, month))
        return _make_twse_history_raw(year, month, days_by_month.get((year, month), 0))

    monkeypatch.setattr(twse_history, "fetch", fake_twse)
    monkeypatch.setattr(
        tpex_history,
        "fetch",
        lambda ticker, year, month: _load("tpex_history_nodata.json"),
    )

    collected = jobs_backfill._collect_ticker_history("2330", 35)

    assert len(collected) == 45  # 3 + 21 + 21 跨月累加
    assert calls == [m0, m1, m2]  # 新到舊走訪，且到第三個月即停（達標）
    # 日期正確：每個月的首日與末日都在，且鍵為正確的 ISO 日期。
    for (year, month), n in days_by_month.items():
        first, last = f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{n:02d}"
        assert first in collected
        assert last in collected
        assert collected[last]["close"] == 10.5


def test_collect_history_stops_early_when_target_met(monkeypatch):
    # 前兩個月已湊滿 42 ≥ 35 → 第三個月不再抓（提前停，非月數上限停）。
    m0, m1, _m2 = _recent_months(3)
    days_by_month = {m0: 21, m1: 21}
    calls: list[tuple[int, int]] = []

    def fake_twse(ticker: str, year: int, month: int) -> dict:
        calls.append((year, month))
        return _make_twse_history_raw(year, month, days_by_month.get((year, month), 0))

    monkeypatch.setattr(twse_history, "fetch", fake_twse)
    monkeypatch.setattr(
        tpex_history,
        "fetch",
        lambda ticker, year, month: _load("tpex_history_nodata.json"),
    )

    collected = jobs_backfill._collect_ticker_history("2330", 35)

    assert len(collected) == 42
    assert calls == [m0, m1]  # 達標即停，第三個月從未被抓


def test_collect_history_stops_at_month_cap(monkeypatch):
    # target 遠大於可得（每月僅 1 交易日）→ 湊不滿也停手，走滿 _MAX_MONTHS(6) 個月即止。
    months = _recent_months(jobs_backfill._MAX_MONTHS)
    calls: list[tuple[int, int]] = []

    def fake_twse(ticker: str, year: int, month: int) -> dict:
        calls.append((year, month))
        return _make_twse_history_raw(year, month, 1)

    monkeypatch.setattr(twse_history, "fetch", fake_twse)
    monkeypatch.setattr(
        tpex_history,
        "fetch",
        lambda ticker, year, month: _load("tpex_history_nodata.json"),
    )

    collected = jobs_backfill._collect_ticker_history("2330", 999)

    assert len(collected) == jobs_backfill._MAX_MONTHS  # 每月 1 日 × 6 月
    assert calls == months  # 走滿月數上限，未提前停


# --------------------------------------------------------------------------- #
# backfill_institutional — walk recent calendar days
# --------------------------------------------------------------------------- #


def test_backfill_institutional_writes_recent_days(monkeypatch, eng):
    t86_raw = _load("twse_t86.json")
    tpex_raw = _load("tpex_institutional.json")
    monkeypatch.setattr(twse_t86, "fetch", lambda date: t86_raw)
    monkeypatch.setattr(tpex_institutional, "fetch", lambda date: tpex_raw)

    with Session(eng) as s:
        _seed_companies(s, ["2330", "3081"])
        written = jobs_backfill.backfill_institutional(s, days=3)
        s.commit()

    with Session(eng) as s:
        # 3 個日曆日 × 2 檔（每日 upsert）→ 6 列，跨 3 個不同日期。
        rows = s.query(models.InstitutionalFlow).all()
        assert {r.ticker for r in rows} == {"2330", "3081"}
        assert len({r.date for r in rows}) == 3
        assert s.query(models.InstitutionalFlow).count() == 6
        assert written == 6


def test_backfill_institutional_skips_failing_day(monkeypatch, eng):
    t86_raw = _load("twse_t86.json")
    tpex_raw = _load("tpex_institutional.json")
    today = datetime.now(ZoneInfo("Asia/Taipei")).date().isoformat()

    def flaky_t86(date: str) -> dict:
        if date == today:  # 只讓「今天」這一天壞掉
            raise _common.SourceFetchError("TWSE-T86", "連線失敗")
        return t86_raw

    monkeypatch.setattr(twse_t86, "fetch", flaky_t86)
    monkeypatch.setattr(tpex_institutional, "fetch", lambda date: tpex_raw)

    with Session(eng) as s:
        _seed_companies(s, ["2330", "3081"])
        jobs_backfill.backfill_institutional(s, days=3)  # 壞一天不中止其餘兩天
        s.commit()

    with Session(eng) as s:
        # 今天被跳過 → 只剩 2 天資料。
        assert len({r.date for r in s.query(models.InstitutionalFlow).all()}) == 2


# --------------------------------------------------------------------------- #
# fetch_indices — Yahoo 指數快照 into index_snapshots
# --------------------------------------------------------------------------- #


def test_fetch_indices_upserts_all_symbols(monkeypatch, eng):
    twii = _load("yahoo_twii.json")
    # 每檔都回同一份 raw；parse 以 symbol 決定 name/PK，故 7 檔各寫一列。
    monkeypatch.setattr(yahoo_indices, "fetch", lambda symbol: twii)

    with Session(eng) as s:
        jobs_daily.fetch_indices(s)
        s.commit()

    with Session(eng) as s:
        snaps = s.query(models.IndexSnapshot).all()
        assert len(snaps) == len(yahoo_indices.SYMBOLS) == 7
        twii_snap = s.get(models.IndexSnapshot, "^TWII")
        assert twii_snap is not None
        assert twii_snap.name == "加權指數"  # 名稱來自 SYMBOLS 表，非 Yahoo
        assert twii_snap.price == 45354.61
        # change/pct 由 price - chartPreviousClose(45734.41) 導出
        assert twii_snap.change == pytest.approx(45354.61 - 45734.41, abs=0.01)
        assert twii_snap.fetched_at is not None


def test_fetch_indices_overwrites_existing_symbol(monkeypatch, eng):
    twii = _load("yahoo_twii.json")
    monkeypatch.setattr(yahoo_indices, "fetch", lambda symbol: twii)
    with Session(eng) as s:
        jobs_daily.fetch_indices(s)
        s.commit()
    with Session(eng) as s:
        jobs_daily.fetch_indices(s)  # 重跑覆寫，不新增列
        s.commit()
    with Session(eng) as s:
        assert s.query(models.IndexSnapshot).count() == 7  # symbol PK 覆寫


def test_fetch_indices_skips_single_failing_symbol(monkeypatch, eng):
    twii = _load("yahoo_twii.json")

    def flaky(symbol: str) -> dict:
        if symbol == "^SOX":  # 單一 symbol 失敗
            raise _common.SourceFetchError("Yahoo", "查無資料")
        return twii

    monkeypatch.setattr(yahoo_indices, "fetch", flaky)
    with Session(eng) as s:
        jobs_daily.fetch_indices(s)  # 不因 ^SOX 中止
        s.commit()

    with Session(eng) as s:
        # 6 檔成功、^SOX 被跳過。
        assert s.query(models.IndexSnapshot).count() == 6
        assert s.get(models.IndexSnapshot, "^SOX") is None
        assert s.get(models.IndexSnapshot, "^TWII") is not None


def test_fetch_indices_all_fail_raises(monkeypatch, eng):
    def boom(symbol: str) -> dict:
        raise _common.SourceFetchError("Yahoo", "端點封鎖")

    monkeypatch.setattr(yahoo_indices, "fetch", boom)
    with Session(eng) as s:
        with pytest.raises(RuntimeError):
            jobs_daily.fetch_indices(s)


def test_fetch_indices_skips_null_price(monkeypatch, eng):
    # 成功 fetch/parse 但 price 為 None（meta 缺 regularMarketPrice）→ 跳過（price NOT NULL）。
    priceless = {"chart": {"error": None, "result": [{"meta": {}}]}}
    monkeypatch.setattr(yahoo_indices, "fetch", lambda symbol: priceless)
    with Session(eng) as s:
        # 全部 7 檔皆 price None → 等同全失敗 → raise。
        with pytest.raises(RuntimeError):
            jobs_daily.fetch_indices(s)


# --------------------------------------------------------------------------- #
# fetch_market_stats — BFI82U + MI_MARGN into market_flows / margin_balances
# --------------------------------------------------------------------------- #


def _patch_market_stats(monkeypatch, bfi_raw, margin_raw) -> None:
    monkeypatch.setattr(twse_bfi82u, "fetch", lambda date: bfi_raw)
    monkeypatch.setattr(twse_margin, "fetch", lambda date: margin_raw)


def test_fetch_market_stats_upserts_both(monkeypatch, eng):
    _patch_market_stats(
        monkeypatch, _load("twse_bfi82u.json"), _load("twse_margin.json")
    )
    today = _taipei_today()

    with Session(eng) as s:
        jobs_daily.fetch_market_stats(s)
        s.commit()

    with Session(eng) as s:
        flows = s.query(models.MarketFlow).all()
        # BFI82U fixture 有 6 身份別，「合計」跳過 → 5 列入庫。
        assert len(flows) == 5
        assert all(f.unit != "合計" for f in flows)
        assert all(f.date == today for f in flows)
        investa = s.get(models.MarketFlow, (today, "投信"))
        assert investa is not None
        assert investa.net == 19_900_600_663
        # margin：3 個 item 全入庫。
        margins = s.query(models.MarginBalance).all()
        assert len(margins) == 3
        m = s.get(models.MarginBalance, (today, "融資金額(仟元)"))
        assert m is not None
        assert m.today_balance == 619_648_244


def test_fetch_market_stats_is_idempotent(monkeypatch, eng):
    _patch_market_stats(
        monkeypatch, _load("twse_bfi82u.json"), _load("twse_margin.json")
    )
    with Session(eng) as s:
        jobs_daily.fetch_market_stats(s)
        s.commit()
    with Session(eng) as s:
        jobs_daily.fetch_market_stats(s)  # 同日重跑
        s.commit()
    with Session(eng) as s:
        assert s.query(models.MarketFlow).count() == 5
        assert s.query(models.MarginBalance).count() == 3


def test_fetch_market_stats_holiday_both_empty(monkeypatch, eng):
    _patch_market_stats(
        monkeypatch,
        _load("twse_bfi82u_holiday.json"),
        _load("twse_margin_holiday.json"),
    )
    with Session(eng) as s:
        jobs_daily.fetch_market_stats(s)  # 假日兩者空，不 raise
        s.commit()
    with Session(eng) as s:
        assert s.query(models.MarketFlow).count() == 0
        assert s.query(models.MarginBalance).count() == 0


def test_fetch_market_stats_one_source_fails_other_persists(monkeypatch, eng):
    # BFI82U 失敗，margin 成功：margin 的資料仍須 stage 且不 raise。
    def boom(date: str) -> dict:
        raise _common.SourceFetchError("TWSE-BFI82U", "連線失敗")

    monkeypatch.setattr(twse_bfi82u, "fetch", boom)
    monkeypatch.setattr(twse_margin, "fetch", lambda date: _load("twse_margin.json"))

    with Session(eng) as s:
        jobs_daily.fetch_market_stats(s)  # 單來源失敗不 raise
        s.commit()

    with Session(eng) as s:
        assert s.query(models.MarketFlow).count() == 0  # BFI82U 無資料
        assert s.query(models.MarginBalance).count() == 3  # margin 照常入庫


def test_fetch_market_stats_both_fail_raises(monkeypatch, eng):
    def boom(date: str) -> dict:
        raise _common.SourceFetchError("TWSE", "連線失敗")

    monkeypatch.setattr(twse_bfi82u, "fetch", boom)
    monkeypatch.setattr(twse_margin, "fetch", boom)

    with Session(eng) as s:
        with pytest.raises(_common.SourceFetchError):
            jobs_daily.fetch_market_stats(s)


# --------------------------------------------------------------------------- #
# fetch_mops — 上市 + 上櫃 重大訊息 into mops_announcements
# --------------------------------------------------------------------------- #


def test_fetch_mops_inserts_merged_markets(monkeypatch, eng):
    listed = _load("mops_listed.json")
    otc = _load("mops_otc.json")
    monkeypatch.setattr(mops, "fetch_listed", lambda: listed)
    monkeypatch.setattr(mops, "fetch_otc", lambda: otc)

    with Session(eng) as s:
        jobs_daily.fetch_mops(s)
        s.commit()

    with Session(eng) as s:
        rows = s.query(models.MopsAnnouncement).all()
        # 不過濾公司：兩市場 parse 出的列全入庫。
        expected = len(mops.parse(listed + otc))
        assert expected > 0
        assert len(rows) == expected
        tickers = {r.ticker for r in rows}
        assert "1721" in tickers  # 上市三晃
        assert "4530" in tickers  # 上櫃宏易


def test_fetch_mops_skips_duplicates_on_rerun(monkeypatch, eng):
    listed = _load("mops_listed.json")
    monkeypatch.setattr(mops, "fetch_listed", lambda: listed)
    monkeypatch.setattr(mops, "fetch_otc", lambda: [])

    with Session(eng) as s:
        jobs_daily.fetch_mops(s)
        s.commit()
    with Session(eng) as s:
        first = s.query(models.MopsAnnouncement).count()
    with Session(eng) as s:
        jobs_daily.fetch_mops(s)  # 重跑：撞 unique 全跳過
        s.commit()
    with Session(eng) as s:
        assert s.query(models.MopsAnnouncement).count() == first


def test_fetch_mops_one_market_fails_other_inserts(monkeypatch, eng):
    listed = _load("mops_listed.json")

    def boom() -> list[dict]:
        raise _common.SourceFetchError("MOPS-上櫃", "連線失敗")

    monkeypatch.setattr(mops, "fetch_listed", lambda: listed)
    monkeypatch.setattr(mops, "fetch_otc", boom)

    with Session(eng) as s:
        jobs_daily.fetch_mops(s)  # 單市場失敗不中止
        s.commit()

    with Session(eng) as s:
        assert s.query(models.MopsAnnouncement).count() == len(mops.parse(listed))


def test_fetch_mops_both_markets_fail_raises(monkeypatch, eng):
    def boom() -> list[dict]:
        raise _common.SourceFetchError("MOPS", "連線失敗")

    monkeypatch.setattr(mops, "fetch_listed", boom)
    monkeypatch.setattr(mops, "fetch_otc", boom)

    with Session(eng) as s:
        with pytest.raises(_common.SourceFetchError):
            jobs_daily.fetch_mops(s)


def test_fetch_mops_warns_on_field_drift(monkeypatch, eng):
    # raw 非空但 parse 全 skip（發言日期/時間欄漂移）→ log warning，不入庫。
    drifted = [{"公司代號": "1721", "主旨 ": "x", "壞日期": "1150711", "壞時間": "70003"}]
    monkeypatch.setattr(mops, "fetch_listed", lambda: drifted)
    monkeypatch.setattr(mops, "fetch_otc", lambda: [])

    # 專案用 loguru（非 stdlib logging），以 sink 收集訊息。
    from loguru import logger

    messages: list[str] = []
    sink_id = logger.add(lambda m: messages.append(m), level="WARNING")
    try:
        with Session(eng) as s:
            jobs_daily.fetch_mops(s)
            s.commit()
    finally:
        logger.remove(sink_id)

    with Session(eng) as s:
        assert s.query(models.MopsAnnouncement).count() == 0
    assert any("欄名漂移" in msg for msg in messages)


def test_fetch_mops_truncates_over_limit(monkeypatch, eng):
    # 合成 > 500 筆，各列唯一（不同 title），驗證只取前 500。
    big = [
        {
            "公司代號": "1721",
            "公司名稱": "測試",
            "主旨 ": f"公告事項 {i}",
            "發言日期": "1150711",
            "發言時間": "070003",
        }
        for i in range(600)
    ]
    monkeypatch.setattr(mops, "fetch_listed", lambda: big)
    monkeypatch.setattr(mops, "fetch_otc", lambda: [])

    with Session(eng) as s:
        jobs_daily.fetch_mops(s)
        s.commit()

    with Session(eng) as s:
        assert s.query(models.MopsAnnouncement).count() == 500


# --------------------------------------------------------------------------- #
# backfill_market_stats — walk recent calendar days
# --------------------------------------------------------------------------- #


def test_backfill_market_stats_writes_recent_days(monkeypatch, eng):
    monkeypatch.setattr(twse_bfi82u, "fetch", lambda date: _load("twse_bfi82u.json"))
    monkeypatch.setattr(twse_margin, "fetch", lambda date: _load("twse_margin.json"))

    with Session(eng) as s:
        written = jobs_backfill.backfill_market_stats(s, days=3)
        s.commit()

    with Session(eng) as s:
        # 每日 5 市場流 + 3 信用列 = 8；3 日 = 24 列。
        assert s.query(models.MarketFlow).count() == 15
        assert s.query(models.MarginBalance).count() == 9
        assert len({f.date for f in s.query(models.MarketFlow).all()}) == 3
        assert written == 24


def test_backfill_market_stats_skips_failing_day(monkeypatch, eng):
    today = datetime.now(ZoneInfo("Asia/Taipei")).date().isoformat()

    def flaky_bfi(date: str) -> dict:
        if date == today:  # 只讓今天壞
            raise _common.SourceFetchError("TWSE-BFI82U", "連線失敗")
        return _load("twse_bfi82u.json")

    monkeypatch.setattr(twse_bfi82u, "fetch", flaky_bfi)
    monkeypatch.setattr(twse_margin, "fetch", lambda date: _load("twse_margin.json"))

    with Session(eng) as s:
        jobs_backfill.backfill_market_stats(s, days=3)  # 壞一天不中止其餘
        s.commit()

    with Session(eng) as s:
        # 今天整天被跳過（bfi 先 raise，margin 也不寫）→ 只剩 2 天。
        assert len({f.date for f in s.query(models.MarketFlow).all()}) == 2


# --------------------------------------------------------------------------- #
# fetch_per — 上市 BWIBBU + 上櫃 peratio into per_daily（兩來源隔離）
# --------------------------------------------------------------------------- #


def _patch_per_sources(monkeypatch, listed_raw, otc_raw) -> None:
    monkeypatch.setattr(twse_per, "fetch", lambda: listed_raw)
    monkeypatch.setattr(tpex_per, "fetch", lambda: otc_raw)


def test_fetch_per_upserts_both_markets(monkeypatch, eng):
    _patch_per_sources(
        monkeypatch, _load("twse_bwibbu_all.json"), _load("tpex_peratio.json")
    )
    with Session(eng) as s:
        # 2330 在上市 BWIBBU、3081 在上櫃 peratio；其餘 fixtures 代號未 seed，應被過濾。
        _seed_companies(s, ["2330", "3081"])
        jobs_daily.fetch_per(s)
        s.commit()

    with Session(eng) as s:
        # 兩來源 row Date 1150709 → 2026-07-09（row Date 優先於呼叫端 fallback）。
        p2330 = s.get(models.PerDaily, ("2330", "2026-07-09"))
        p3081 = s.get(models.PerDaily, ("3081", "2026-07-09"))
        assert p2330 is not None
        assert p3081 is not None
        assert p2330.per == pytest.approx(32.47)
        assert p2330.pbr == pytest.approx(10.63)
        assert p2330.dividend_yield == pytest.approx(0.91)
        assert p3081.per == pytest.approx(263.47)
        assert p3081.pbr == pytest.approx(43.76)
        assert p3081.dividend_yield == pytest.approx(0.20)
        tickers = {p.ticker for p in s.query(models.PerDaily).all()}
        assert tickers == {"2330", "3081"}  # 只有已收錄的兩檔


def test_fetch_per_is_idempotent(monkeypatch, eng):
    _patch_per_sources(
        monkeypatch, _load("twse_bwibbu_all.json"), _load("tpex_peratio.json")
    )
    with Session(eng) as s:
        _seed_companies(s, ["2330", "3081"])
        jobs_daily.fetch_per(s)
        s.commit()
    with Session(eng) as s:
        jobs_daily.fetch_per(s)  # 同日重跑 ticker+date PK 覆寫
        s.commit()
    with Session(eng) as s:
        assert s.query(models.PerDaily).count() == 2


def test_fetch_per_one_source_fails_other_persists(monkeypatch, eng):
    # 上市失敗、上櫃成功：上櫃資料仍須 stage 且不 raise（比照 fetch_market_stats）。
    def boom() -> list[dict]:
        raise _common.SourceFetchError("本益比-上市", "連線失敗")

    monkeypatch.setattr(twse_per, "fetch", boom)
    monkeypatch.setattr(tpex_per, "fetch", lambda: _load("tpex_peratio.json"))

    with Session(eng) as s:
        _seed_companies(s, ["2330", "3081"])
        jobs_daily.fetch_per(s)  # 單來源失敗不 raise
        s.commit()

    with Session(eng) as s:
        assert s.query(models.PerDaily).filter_by(ticker="2330").count() == 0
        assert s.query(models.PerDaily).filter_by(ticker="3081").count() == 1


def test_fetch_per_both_fail_raises(monkeypatch, eng):
    def boom() -> list[dict]:
        raise _common.SourceFetchError("本益比", "連線失敗")

    monkeypatch.setattr(twse_per, "fetch", boom)
    monkeypatch.setattr(tpex_per, "fetch", boom)

    with Session(eng) as s:
        _seed_companies(s, ["2330", "3081"])
        with pytest.raises(_common.SourceFetchError):
            jobs_daily.fetch_per(s)


# --------------------------------------------------------------------------- #
# fetch_fundamentals — 上市 + 上櫃 月營收 into fundamentals（兩來源隔離）
# --------------------------------------------------------------------------- #


def _patch_fundamentals_sources(monkeypatch, listed_raw, otc_raw) -> None:
    monkeypatch.setattr(twse_revenue, "fetch", lambda: listed_raw)
    monkeypatch.setattr(tpex_revenue, "fetch", lambda: otc_raw)


def test_fetch_fundamentals_upserts_both_markets(monkeypatch, eng):
    _patch_fundamentals_sources(
        monkeypatch, _load("revenue_listed.json"), _load("revenue_otc.json")
    )
    with Session(eng) as s:
        # 2454 在上市營收、3081 在上櫃營收；其餘 fixtures 代號未 seed，應被過濾。
        _seed_companies(s, ["2454", "3081"])
        jobs_monthly.fetch_fundamentals(s)
        s.commit()

    with Session(eng) as s:
        # 資料年月 11506 → ISO "2026-06"。
        f2454 = s.get(models.Fundamental, ("2454", "2026-06"))
        f3081 = s.get(models.Fundamental, ("3081", "2026-06"))
        assert f2454 is not None
        assert f3081 is not None
        assert f2454.revenue == 58_011_756  # 單位：千元
        assert f2454.yoy == pytest.approx(2.796444693846599)
        assert f3081.revenue == 420_507
        tickers = {f.ticker for f in s.query(models.Fundamental).all()}
        assert tickers == {"2454", "3081"}  # 只有已收錄的兩檔


def test_fetch_fundamentals_pk_overwrite_on_rerun(monkeypatch, eng):
    # (ticker, month) PK 覆寫：晚申報修正值重跑不重複列。
    _patch_fundamentals_sources(monkeypatch, _load("revenue_listed.json"), [])
    with Session(eng) as s:
        _seed_companies(s, ["2454"])
        jobs_monthly.fetch_fundamentals(s)
        s.commit()
    with Session(eng) as s:
        jobs_monthly.fetch_fundamentals(s)
        s.commit()
    with Session(eng) as s:
        assert s.query(models.Fundamental).filter_by(ticker="2454").count() == 1


def test_fetch_fundamentals_one_source_fails_other_persists(monkeypatch, eng):
    def boom() -> list[dict]:
        raise _common.SourceFetchError("月營收-上市", "連線失敗")

    monkeypatch.setattr(twse_revenue, "fetch", boom)
    monkeypatch.setattr(tpex_revenue, "fetch", lambda: _load("revenue_otc.json"))

    with Session(eng) as s:
        _seed_companies(s, ["2454", "3081"])
        jobs_monthly.fetch_fundamentals(s)  # 單來源失敗不 raise
        s.commit()

    with Session(eng) as s:
        assert s.query(models.Fundamental).filter_by(ticker="2454").count() == 0
        assert s.query(models.Fundamental).filter_by(ticker="3081").count() == 1


def test_fetch_fundamentals_both_fail_raises(monkeypatch, eng):
    def boom() -> list[dict]:
        raise _common.SourceFetchError("月營收", "連線失敗")

    monkeypatch.setattr(twse_revenue, "fetch", boom)
    monkeypatch.setattr(tpex_revenue, "fetch", boom)

    with Session(eng) as s:
        with pytest.raises(_common.SourceFetchError):
            jobs_monthly.fetch_fundamentals(s)


# --------------------------------------------------------------------------- #
# fetch_tdcc — 集保股權分散 into major_holders（單來源 job）
# --------------------------------------------------------------------------- #


def _tdcc_csv() -> str:
    return (FIXTURES_DIR / "tdcc_holders.csv").read_text(encoding="utf-8-sig")


def test_fetch_tdcc_upserts_major_holders(monkeypatch, eng):
    monkeypatch.setattr(tdcc_holders, "fetch", _tdcc_csv)
    with Session(eng) as s:
        # parse 以 wanted=收錄公司 過濾；只 seed 兩檔，其餘 csv 代號不入庫。
        _seed_companies(s, ["2330", "3081"])
        jobs_monthly.fetch_tdcc(s)
        s.commit()

    with Session(eng) as s:
        h2330 = s.get(models.MajorHolder, ("2330", "2026-07-03"))
        assert h2330 is not None
        # 2330 級距 12–15 占比合計 = 87.81；holder_count = Σ 級距 1–15 人數。
        assert h2330.ratio_400up == pytest.approx(87.81)
        assert h2330.holder_count == 2_898_020
        tickers = {h.ticker for h in s.query(models.MajorHolder).all()}
        assert tickers == {"2330", "3081"}


def test_fetch_tdcc_is_idempotent(monkeypatch, eng):
    monkeypatch.setattr(tdcc_holders, "fetch", _tdcc_csv)
    with Session(eng) as s:
        _seed_companies(s, ["2330", "3081"])
        jobs_monthly.fetch_tdcc(s)
        s.commit()
    with Session(eng) as s:
        jobs_monthly.fetch_tdcc(s)  # 同週重跑 ticker+week PK 覆寫
        s.commit()
    with Session(eng) as s:
        assert s.query(models.MajorHolder).count() == 2


def test_fetch_tdcc_source_error_propagates(monkeypatch, eng):
    # 單來源 job：SourceFetchError 不吞，往上拋給 runner。
    def boom() -> str:
        raise _common.SourceFetchError("集保股權分散", "連線失敗")

    monkeypatch.setattr(tdcc_holders, "fetch", boom)
    with Session(eng) as s:
        _seed_companies(s, ["2330"])
        with pytest.raises(_common.SourceFetchError):
            jobs_monthly.fetch_tdcc(s)


# --------------------------------------------------------------------------- #
# backfill_per — 每檔月本益比歷史 into per_daily
# --------------------------------------------------------------------------- #


def test_backfill_per_writes_history_and_otc_noop(monkeypatch, eng):
    hist = _load("twse_bwibbu_history.json")  # 2330, 21 交易日 (2026-06)
    nodata = _load("twse_bwibbu_history_nodata.json")
    # 上市端點對 2330 有資料、對上櫃 3081 回無資料（上櫃無個股月檔端點）→ 3081 no-op。
    monkeypatch.setattr(
        twse_per_history,
        "fetch",
        lambda ticker, year, month: hist if ticker == "2330" else nodata,
    )

    with Session(eng) as s:
        _seed_companies(s, ["2330", "3081"])
        written = jobs_backfill.backfill_per(s, months=3)
        s.commit()

    with Session(eng) as s:
        assert s.query(models.PerDaily).filter_by(ticker="2330").count() == 21
        assert s.query(models.PerDaily).filter_by(ticker="3081").count() == 0  # OTC no-op
        assert written == 21
        p = s.get(models.PerDaily, ("2330", "2026-06-01"))
        assert p is not None
        assert p.per == pytest.approx(31.66)
        assert p.pbr == pytest.approx(10.37)
        assert p.dividend_yield == pytest.approx(0.93)


def test_backfill_per_does_not_overwrite_existing_row(monkeypatch, eng):
    hist = _load("twse_bwibbu_history.json")
    nodata = _load("twse_bwibbu_history_nodata.json")
    monkeypatch.setattr(
        twse_per_history,
        "fetch",
        lambda ticker, year, month: hist if ticker == "2330" else nodata,
    )
    with Session(eng) as s:
        _seed_companies(s, ["2330"])
        # 既有列（如 fetch_per 當日已寫）不可被 backfill 覆蓋。
        s.add(
            models.PerDaily(
                ticker="2330", date="2026-06-01", per=999.0, pbr=1.0, dividend_yield=5.0
            )
        )
        s.flush()
        jobs_backfill.backfill_per(s, months=3)
        s.commit()

    with Session(eng) as s:
        p = s.get(models.PerDaily, ("2330", "2026-06-01"))
        assert p.per == 999.0  # 未被覆蓋
        assert s.query(models.PerDaily).filter_by(ticker="2330").count() == 21


def test_backfill_per_skips_failing_ticker(monkeypatch, eng):
    hist = _load("twse_bwibbu_history.json")
    nodata = _load("twse_bwibbu_history_nodata.json")

    def flaky(ticker: str, year: int, month: int) -> dict:
        if ticker == "9999":
            raise _common.SourceFetchError("本益比歷史-上市", "連線失敗")
        return hist if ticker == "2330" else nodata

    monkeypatch.setattr(twse_per_history, "fetch", flaky)

    with Session(eng) as s:
        _seed_companies(s, ["9999", "2330"])
        written = jobs_backfill.backfill_per(s, months=3)  # 不因 9999 中止
        s.commit()

    with Session(eng) as s:
        assert s.query(models.PerDaily).filter_by(ticker="9999").count() == 0
        assert s.query(models.PerDaily).filter_by(ticker="2330").count() == 21
        assert written == 21


def test_backfill_per_all_fail_logs_error(monkeypatch, eng):
    def boom(ticker: str, year: int, month: int) -> dict:
        raise _common.SourceFetchError("本益比歷史-上市", "連線失敗")

    monkeypatch.setattr(twse_per_history, "fetch", boom)

    from loguru import logger

    messages: list[str] = []
    sink_id = logger.add(lambda m: messages.append(m), level="ERROR")
    try:
        with Session(eng) as s:
            _seed_companies(s, ["2330", "3081"])
            written = jobs_backfill.backfill_per(s, months=3)
            s.commit()
    finally:
        logger.remove(sink_id)

    assert written == 0
    assert any("全部" in msg and "失敗" in msg for msg in messages)
