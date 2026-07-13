"""Tests for the yahoo_quotes source — 美股日線 OHLCV (v8 chart, multi-bar).

Fixtures under tests/fixtures/yahoo_quotes_* are real API responses recorded
once via scripts/record_fixtures.py (``_record_yahoo_quotes``):
  * yahoo_quotes_nvda_5d.json — NVDA range=5d, 5 bars (2026-07-06..07-10).
  * yahoo_quotes_404.json     — an unknown/delisted symbol's 404 body
    (chart.error non-null, result=null).

Transport tests monkeypatch ``cffi_requests.get`` (no network) and assert the
error contract is byte-identical to yahoo_indices; parse tests assert the
array→rows mapping, the exchange-local date, null-close skipping and the
in-series change_pct.
"""

import json
from pathlib import Path

import pytest

from app.pipeline.sources import yahoo_quotes
from app.pipeline.sources._common import SourceFetchError

FIXTURES_DIR = Path(__file__).parent / "fixtures"

QUOTE_KEYS = {
    "ticker",
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "change_pct",
}


@pytest.fixture
def nvda_5d() -> dict:
    return json.loads(
        (FIXTURES_DIR / "yahoo_quotes_nvda_5d.json").read_text(encoding="utf-8")
    )


@pytest.fixture
def error_404() -> dict:
    return json.loads(
        (FIXTURES_DIR / "yahoo_quotes_404.json").read_text(encoding="utf-8")
    )


# --- parse ------------------------------------------------------------------


def test_parse_nvda_shape_and_dates(nvda_5d):
    rows = yahoo_quotes.parse(nvda_5d, "NVDA")
    assert len(rows) == 5  # 5 bars, all with a close
    assert all(set(r) == QUOTE_KEYS for r in rows)
    assert all(r["ticker"] == "NVDA" for r in rows)
    # Exchange-local (America/New_York) calendar days, not UTC.
    assert [r["date"] for r in rows] == [
        "2026-07-06",
        "2026-07-07",
        "2026-07-08",
        "2026-07-09",
        "2026-07-10",
    ]


def test_parse_nvda_ohlcv_values(nvda_5d):
    rows = yahoo_quotes.parse(nvda_5d, "NVDA")
    last = rows[-1]  # 2026-07-10
    assert last["open"] == pytest.approx(202.0)
    assert last["high"] == pytest.approx(211.0)
    assert last["low"] == pytest.approx(201.92, abs=0.01)
    assert last["close"] == pytest.approx(210.96, abs=0.01)
    assert last["volume"] == 148_124_000


def test_parse_change_pct_first_bar_none_then_in_series(nvda_5d):
    rows = yahoo_quotes.parse(nvda_5d, "NVDA")
    # First emitted bar has no prior close → None.
    assert rows[0]["change_pct"] is None
    # bar1: (196.93 - 195.55) / 195.55 * 100 = 0.71.
    assert rows[1]["change_pct"] == pytest.approx(0.71, abs=0.01)
    # bar4: (210.96 - 202.78) / 202.78 * 100 = 4.03.
    assert rows[4]["change_pct"] == pytest.approx(4.03, abs=0.01)


def _raw(timestamps, quote, tz="America/New_York"):
    return {
        "chart": {
            "error": None,
            "result": [
                {
                    "meta": {"exchangeTimezoneName": tz},
                    "timestamp": timestamps,
                    "indicators": {"quote": [quote]},
                }
            ],
        }
    }


def test_parse_skips_null_close_bars_and_reprices_from_prev_valid():
    # Middle bar has a null close: it is dropped, and the following bar's
    # change_pct is computed against the *previous valid* close (100 -> 110),
    # not the skipped bar.
    raw = _raw(
        [1_783_344_600, 1_783_431_000, 1_783_517_400],
        {
            "open": [10, 20, 30],
            "high": [10, 20, 30],
            "low": [10, 20, 30],
            "close": [100.0, None, 110.0],
            "volume": [1, 2, 3],
        },
    )
    rows = yahoo_quotes.parse(raw, "TEST")
    assert len(rows) == 2  # null-close bar dropped
    assert rows[0]["close"] == 100.0
    assert rows[0]["change_pct"] is None  # first emitted
    assert rows[1]["close"] == 110.0
    assert rows[1]["change_pct"] == pytest.approx(10.0)  # 110 vs 100, not vs None


def test_parse_zero_prev_close_guards_division():
    raw = _raw(
        [1_783_344_600, 1_783_431_000],
        {
            "open": [0, 5],
            "high": [0, 5],
            "low": [0, 5],
            "close": [0.0, 5.0],
            "volume": [1, 2],
        },
    )
    rows = yahoo_quotes.parse(raw, "TEST")
    assert rows[0]["change_pct"] is None  # first bar
    assert rows[1]["change_pct"] is None  # prev close 0 → division guard


def test_parse_uses_exchange_timezone_for_date():
    # 1783389600 = 2026-07-07 02:00 UTC == 2026-07-06 22:00 America/New_York.
    # A UTC-based date would tag this bar 07-07; the exchange day is 07-06.
    raw = _raw(
        [1_783_389_600],
        {"open": [1], "high": [1], "low": [1], "close": [1.0], "volume": [1]},
    )
    rows = yahoo_quotes.parse(raw, "TEST")
    assert rows[0]["date"] == "2026-07-06"  # exchange day, not the UTC 07-07


def test_parse_missing_timezone_falls_back_to_new_york():
    raw = {
        "chart": {
            "error": None,
            "result": [
                {
                    "meta": {},  # no exchangeTimezoneName
                    "timestamp": [1_783_389_600],
                    "indicators": {
                        "quote": [
                            {
                                "open": [1],
                                "high": [1],
                                "low": [1],
                                "close": [1.0],
                                "volume": [1],
                            }
                        ]
                    },
                }
            ],
        }
    }
    rows = yahoo_quotes.parse(raw, "TEST")
    assert rows[0]["date"] == "2026-07-06"  # New_York fallback


def test_parse_404_body_raises(error_404):
    # Recorded unknown-symbol response: chart.error={'code':'Not Found',...}.
    with pytest.raises(SourceFetchError) as excinfo:
        yahoo_quotes.parse(error_404, "SPACEX")
    assert "Yahoo" in str(excinfo.value)


@pytest.mark.parametrize(
    "raw",
    [
        {"chart": {"result": [], "error": None}},  # empty result list
        {"chart": {"result": None, "error": None}},  # null result
        {"chart": {"error": {"code": "x"}}},  # error set
        {"chart": {}},  # missing both
        {},  # no chart at all
    ],
)
def test_parse_empty_or_errored_result_raises(raw):
    with pytest.raises(SourceFetchError):
        yahoo_quotes.parse(raw, "NVDA")


def test_parse_empty_timestamp_returns_empty_list():
    # A valid result with no bars parses to [] (not an error).
    raw = _raw([], {"open": [], "high": [], "low": [], "close": [], "volume": []})
    assert yahoo_quotes.parse(raw, "NVDA") == []


# --- fetch (transport, no network) ------------------------------------------


class _FakeCffiResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def test_fetch_uses_chrome_impersonation_and_range(monkeypatch, nvda_5d):
    captured = {}

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return _FakeCffiResponse(payload=nvda_5d)

    monkeypatch.setattr(yahoo_quotes.cffi_requests, "get", fake_get)
    monkeypatch.setattr(yahoo_quotes.time, "sleep", lambda _s: None)  # 不真睡
    raw = yahoo_quotes.fetch("NVDA", range="6mo")
    assert raw == nvda_5d
    assert "/v8/finance/chart/NVDA" in captured["url"]
    assert "interval=1d" in captured["url"] and "range=6mo" in captured["url"]
    assert captured["kwargs"]["impersonate"] == "chrome"


def test_fetch_default_range_is_5d(monkeypatch, nvda_5d):
    captured = {}

    def fake_get(url, **kw):
        captured["url"] = url
        return _FakeCffiResponse(payload=nvda_5d)

    monkeypatch.setattr(yahoo_quotes.cffi_requests, "get", fake_get)
    monkeypatch.setattr(yahoo_quotes.time, "sleep", lambda _s: None)
    yahoo_quotes.fetch("NVDA")
    assert "range=5d" in captured["url"]


def test_fetch_sleeps_rate_limit(monkeypatch, nvda_5d):
    slept = []
    monkeypatch.setattr(
        yahoo_quotes.cffi_requests,
        "get",
        lambda url, **kw: _FakeCffiResponse(payload=nvda_5d),
    )
    monkeypatch.setattr(yahoo_quotes.time, "sleep", slept.append)
    yahoo_quotes.fetch("NVDA")
    # Rate limit is built into fetch() — 0.3s, tighter than the index source.
    assert slept == [yahoo_quotes._RATE_LIMIT_SECONDS] and slept == [0.3]


def test_fetch_wraps_non_200(monkeypatch):
    # e.g. the 404 an unknown symbol returns, or the TLS-fingerprint 429.
    monkeypatch.setattr(
        yahoo_quotes.cffi_requests,
        "get",
        lambda url, **kw: _FakeCffiResponse(status_code=404, text="Not Found"),
    )
    monkeypatch.setattr(yahoo_quotes.time, "sleep", lambda _s: None)
    with pytest.raises(SourceFetchError) as excinfo:
        yahoo_quotes.fetch("SPACEX")
    assert excinfo.value.status_code == 404
    assert "Yahoo" in str(excinfo.value)


def test_fetch_wraps_invalid_json(monkeypatch):
    monkeypatch.setattr(
        yahoo_quotes.cffi_requests,
        "get",
        lambda url, **kw: _FakeCffiResponse(payload=None, text="<html>block</html>"),
    )
    monkeypatch.setattr(yahoo_quotes.time, "sleep", lambda _s: None)
    with pytest.raises(SourceFetchError) as excinfo:
        yahoo_quotes.fetch("NVDA")
    assert excinfo.value.status_code == 200


def test_fetch_wraps_connection_error(monkeypatch):
    def boom(url, **kw):
        raise yahoo_quotes.cffi_requests.exceptions.RequestException("dns fail")

    monkeypatch.setattr(yahoo_quotes.cffi_requests, "get", boom)
    monkeypatch.setattr(yahoo_quotes.time, "sleep", lambda _s: None)
    with pytest.raises(SourceFetchError) as excinfo:
        yahoo_quotes.fetch("NVDA")
    assert "Yahoo" in str(excinfo.value)


def test_fetch_wraps_non_dict_json(monkeypatch):
    monkeypatch.setattr(
        yahoo_quotes.cffi_requests,
        "get",
        lambda url, **kw: _FakeCffiResponse(payload=[1, 2, 3]),
    )
    monkeypatch.setattr(yahoo_quotes.time, "sleep", lambda _s: None)
    with pytest.raises(SourceFetchError) as excinfo:
        yahoo_quotes.fetch("NVDA")
    assert excinfo.value.status_code == 200
    assert "Yahoo" in str(excinfo.value)
