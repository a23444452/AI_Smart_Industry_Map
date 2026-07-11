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
from app.pipeline import jobs, jobs_backfill
from app.pipeline.sources import (
    _common,
    tpex,
    tpex_history,
    tpex_institutional,
    twse,
    twse_history,
    twse_t86,
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
