"""Tests for the fetch_tw_quotes job — TWSE+TPEx close data into quotes_daily.

No network: twse.fetch / tpex.fetch are monkeypatched to return the recorded
fixtures' raw row lists. The job then parses, filters to known companies, and
upserts quotes_daily. It must obey the runner transaction contract (no
commit/rollback inside the fn) — tests drive commits explicitly.
"""

import json
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.db import models
from app.db.base import Base, make_engine
from app.pipeline import jobs
from app.pipeline.sources import _common, tpex, twse

FIXTURES_DIR = Path(__file__).parent / "fixtures"


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
