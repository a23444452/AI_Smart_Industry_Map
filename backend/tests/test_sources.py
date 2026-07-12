"""Tests for TWSE/TPEx source clients — parsing only, no network.

Fixtures under tests/fixtures/ are real API responses recorded once via
scripts/record_fixtures.py (first 5 rows + a known ticker).
"""

import datetime
import json
from pathlib import Path

import httpx
import pytest

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
from app.pipeline.sources._common import SourceFetchError

FIXTURES_DIR = Path(__file__).parent / "fixtures"

NEUTRAL_KEYS = {
    "ticker",
    "name",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "change_pct",
    "date",
}


@pytest.fixture
def twse_fixture() -> list[dict]:
    return json.loads(
        (FIXTURES_DIR / "twse_stock_day_all.json").read_text(encoding="utf-8")
    )


@pytest.fixture
def tpex_fixture() -> list[dict]:
    return json.loads(
        (FIXTURES_DIR / "tpex_daily_close.json").read_text(encoding="utf-8")
    )


def test_parse_twse(twse_fixture):
    rows = twse.parse(twse_fixture)
    r = next(x for x in rows if x["ticker"] == "2330")
    assert set(r) == NEUTRAL_KEYS
    assert r["close"] > 0 and abs(r["change_pct"]) < 30
    assert r["name"] == "台積電"
    assert r["date"] == "2026-07-09"  # ROC 1150709 -> ISO
    assert r["volume"] == 34681018


def test_parse_tpex(tpex_fixture):
    rows = tpex.parse(tpex_fixture)
    r = next(x for x in rows if x["ticker"] == "3081")
    assert set(r) == NEUTRAL_KEYS
    assert r["close"] > 0 and abs(r["change_pct"]) < 30
    assert r["name"] == "聯亞"
    assert r["date"] == "2026-07-09"


def test_twse_change_pct_matches_manual(twse_fixture):
    # 2330: Change=-50, Close=2415 -> prev close 2465 -> -50/2465*100
    rows = twse.parse(twse_fixture)
    r = next(x for x in rows if x["ticker"] == "2330")
    assert r["change_pct"] == pytest.approx(-50 / 2465 * 100, abs=1e-9)


def test_tpex_change_pct_handles_signed_change(tpex_fixture):
    # 3081: Change="-90.00 " (signed, trailing space), Close=2005 -> prev 2095
    rows = tpex.parse(tpex_fixture)
    r = next(x for x in rows if x["ticker"] == "3081")
    assert r["change_pct"] == pytest.approx(-90 / 2095 * 100, abs=1e-9)


def test_parse_handles_dash_prices():
    # Suspended / no-trade row: TWSE uses "--" in price columns.
    dash = [
        {
            "Date": "1150709",
            "Code": "9999",
            "Name": "停牌股",
            "TradeVolume": "0",
            "TradeValue": "0",
            "OpeningPrice": "--",
            "HighestPrice": "--",
            "LowestPrice": "--",
            "ClosingPrice": "--",
            "Change": "--",
            "Transaction": "0",
        }
    ]
    rows = twse.parse(dash)
    assert rows[0]["close"] is None
    assert rows[0]["open"] is None
    assert rows[0]["change_pct"] is None


def test_tpex_handles_empty_prices():
    # No-trade row: empty-string price columns -> None.
    empty = [
        {
            "Date": "1150709",
            "SecuritiesCompanyCode": "8888",
            "CompanyName": "無成交",
            "Close": "",
            "Change": "",
            "Open": "",
            "High": "",
            "Low": "",
            "TradingShares": "0",
        }
    ]
    rows = tpex.parse(empty)
    assert rows[0]["close"] is None
    assert rows[0]["change_pct"] is None


def _mock_get(monkeypatch, content: bytes):
    """Make httpx.Client.get return a canned 200 response (no network)."""

    def fake_get(self, url, **kwargs):
        return httpx.Response(
            200,
            content=content,
            headers={"Content-Type": "application/json"},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx.Client, "get", fake_get)


def test_get_json_wraps_invalid_json_body(monkeypatch):
    # 200 but body is not valid JSON (e.g. maintenance HTML page).
    _mock_get(monkeypatch, b"<html>maintenance</html>")
    with pytest.raises(SourceFetchError) as excinfo:
        _common.get_json("https://example.invalid/x", source="TWSE")
    assert excinfo.value.status_code == 200
    assert "TWSE" in str(excinfo.value)


def test_get_json_wraps_non_list_body(monkeypatch):
    # 200 with valid JSON that is not the expected list-of-rows shape.
    _mock_get(monkeypatch, b'{"error": "rate limited"}')
    with pytest.raises(SourceFetchError) as excinfo:
        _common.get_json("https://example.invalid/x", source="TPEx")
    assert excinfo.value.status_code == 200
    assert "TPEx" in str(excinfo.value)


# --- 三大法人 (institutional net flows) -------------------------------------

INSTI_KEYS = {"ticker", "name", "foreign_net", "trust_net", "dealer_net", "date"}


@pytest.fixture
def t86_fixture() -> dict:
    return json.loads((FIXTURES_DIR / "twse_t86.json").read_text(encoding="utf-8"))


@pytest.fixture
def t86_holiday_fixture() -> dict:
    return json.loads(
        (FIXTURES_DIR / "twse_t86_holiday.json").read_text(encoding="utf-8")
    )


@pytest.fixture
def tpex_insti_fixture() -> dict:
    return json.loads(
        (FIXTURES_DIR / "tpex_institutional.json").read_text(encoding="utf-8")
    )


@pytest.fixture
def tpex_insti_holiday_fixture() -> dict:
    return json.loads(
        (FIXTURES_DIR / "tpex_institutional_holiday.json").read_text(encoding="utf-8")
    )


def test_parse_t86(t86_fixture):
    rows = twse_t86.parse(t86_fixture, "2026-07-09")
    r = next(x for x in rows if x["ticker"] == "2330")
    assert set(r) == INSTI_KEYS
    assert r["name"] == "台積電"  # trailing pad stripped
    assert r["date"] == "2026-07-09"
    # foreign = 外陸資淨(不含外資自營商) + 外資自營商淨; commas + negative handled
    assert r["foreign_net"] == -12_748_541 + 0
    assert r["trust_net"] == 43_225
    # dealer = 自營商合計 (自行 905 + 避險 88,958)
    assert r["dealer_net"] == 89_863


def test_t86_three_institutions_sum_to_total(t86_fixture):
    # Invariant: foreign + trust + dealer == 三大法人買賣超股數合計 (fixture idx18).
    r = next(x for x in twse_t86.parse(t86_fixture, "2026-07-09") if x["ticker"] == "2330")
    assert r["foreign_net"] + r["trust_net"] + r["dealer_net"] == -12_615_453


def test_t86_foreign_net_matches_manual(t86_fixture):
    # Manual: 外陸資買進 16,267,509 − 賣出 29,016,050 = -12,748,541 (idx4), +0 dealer.
    r = next(x for x in twse_t86.parse(t86_fixture, "2026-07-09") if x["ticker"] == "2330")
    assert r["foreign_net"] == 16_267_509 - 29_016_050


def test_t86_holiday_returns_empty(t86_holiday_fixture):
    # stat != "OK" (no data key) -> empty list, no raise.
    assert twse_t86.parse(t86_holiday_fixture, "2026-07-11") == []


def test_t86_field_names_with_whitespace_still_parse(t86_fixture):
    # Header labels with incidental whitespace must still map correctly (M3).
    padded = {**t86_fixture, "fields": [f"  {f} " for f in t86_fixture["fields"]]}
    r = next(x for x in twse_t86.parse(padded, "2026-07-09") if x["ticker"] == "2330")
    assert r["foreign_net"] == -12_748_541
    assert r["dealer_net"] == 89_863


def test_t86_missing_ticker_field_raises(t86_fixture):
    # ticker/name header columns disappearing is structural drift -> raise (M3).
    drifted = {
        **t86_fixture,
        "fields": ["改名代號", *t86_fixture["fields"][1:]],
    }
    with pytest.raises(SourceFetchError) as excinfo:
        twse_t86.parse(drifted, "2026-07-09")
    assert "TWSE-T86" in str(excinfo.value)


def test_parse_tpex_institutional(tpex_insti_fixture):
    rows = tpex_institutional.parse(tpex_insti_fixture, "2026-07-09")
    r = next(x for x in rows if x["ticker"] == "3081")
    assert set(r) == INSTI_KEYS
    assert r["name"] == "聯亞"
    assert r["date"] == "2026-07-09"
    assert r["foreign_net"] == -453_275  # 外資及陸資合計 (already incl. foreign dealer)
    assert r["trust_net"] == 84_000
    assert r["dealer_net"] == 191  # 自營商合計 (自行 3,000 + 避險 -2,809)


def test_tpex_institutional_sum_to_total(tpex_insti_fixture):
    r = next(
        x
        for x in tpex_institutional.parse(tpex_insti_fixture, "2026-07-09")
        if x["ticker"] == "3081"
    )
    assert r["foreign_net"] + r["trust_net"] + r["dealer_net"] == -369_084


def test_tpex_institutional_holiday_returns_empty(tpex_insti_holiday_fixture):
    # Empty tables[0].data (stat stays "ok") -> empty list, no raise.
    assert tpex_institutional.parse(tpex_insti_holiday_fixture, "2026-07-11") == []


def test_tpex_institutional_non_ok_stat_returns_empty(tpex_insti_fixture):
    # stat other than "ok" (case-insensitive) -> holiday semantics, [] (M5).
    assert tpex_institutional.parse({**tpex_insti_fixture, "stat": "error"}, "2026-07-09") == []
    ok_upper = {**tpex_insti_fixture, "stat": "OK"}
    assert len(tpex_institutional.parse(ok_upper, "2026-07-09")) > 0


@pytest.mark.parametrize(
    "mutate",
    [
        lambda f: f[:23],  # column removed -> count drift
        lambda f: [*f[:10], "買進股數", *f[11:]],  # idx10 no longer a net column
        lambda f: [*f[:22], "買進股數", f[23]],  # idx22 no longer a net column
    ],
)
def test_tpex_institutional_field_drift_raises(tpex_insti_fixture, mutate):
    # Column drift needs human attention -> raise, never silently return [] (I1).
    table = tpex_insti_fixture["tables"][0]
    drifted = {
        **tpex_insti_fixture,
        "tables": [{**table, "fields": mutate(list(table["fields"]))}],
    }
    with pytest.raises(SourceFetchError) as excinfo:
        tpex_institutional.parse(drifted, "2026-07-09")
    assert "TPEx" in str(excinfo.value)


def test_t86_fetch_builds_yyyymmdd_url(monkeypatch):
    captured = {}

    def fake_get_json_dict(url, *, source):
        captured["url"] = url
        captured["source"] = source
        return {"stat": "OK", "fields": [], "data": []}

    monkeypatch.setattr(_common, "get_json_dict", fake_get_json_dict)
    twse_t86.fetch("2026-07-09")
    assert "date=20260709" in captured["url"]
    assert captured["source"] == "TWSE-T86"


def test_tpex_institutional_fetch_builds_roc_url(monkeypatch):
    captured = {}

    def fake_get_json_dict(url, *, source):
        captured["url"] = url
        return {"stat": "ok", "tables": [{"fields": [], "data": []}]}

    monkeypatch.setattr(_common, "get_json_dict", fake_get_json_dict)
    tpex_institutional.fetch("2026-07-09")
    assert "date=115/07/09" in captured["url"] or "date=115%2F07%2F09" in captured["url"]


def test_get_json_dict_wraps_non_dict_body(monkeypatch):
    # 200 whose JSON is a list, not the expected {stat, ...} dict.
    _mock_get(monkeypatch, b"[1, 2, 3]")
    with pytest.raises(SourceFetchError) as excinfo:
        _common.get_json_dict("https://example.invalid/x", source="TWSE-T86")
    assert excinfo.value.status_code == 200
    assert "TWSE-T86" in str(excinfo.value)


# --- 個股歷史行情 (per-stock monthly OHLCV history, backfill source) --------

HISTORY_KEYS = {
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
def twse_history_fixture() -> dict:
    return json.loads(
        (FIXTURES_DIR / "twse_history.json").read_text(encoding="utf-8")
    )


@pytest.fixture
def twse_history_nodata_fixture() -> dict:
    return json.loads(
        (FIXTURES_DIR / "twse_history_nodata.json").read_text(encoding="utf-8")
    )


@pytest.fixture
def tpex_history_fixture() -> dict:
    return json.loads(
        (FIXTURES_DIR / "tpex_history.json").read_text(encoding="utf-8")
    )


@pytest.fixture
def tpex_history_nodata_fixture() -> dict:
    return json.loads(
        (FIXTURES_DIR / "tpex_history_nodata.json").read_text(encoding="utf-8")
    )


def test_roc_slash_to_iso():
    assert _common.roc_slash_to_iso("115/06/03") == "2026-06-03"
    assert _common.roc_slash_to_iso("115/6/3") == "2026-06-03"  # non-padded
    assert _common.roc_slash_to_iso("") is None
    assert _common.roc_slash_to_iso("--") is None
    assert _common.roc_slash_to_iso("115/13/40") is None  # out of range


def test_parse_twse_history_shape(twse_history_fixture):
    rows = twse_history.parse(twse_history_fixture, "2330")
    assert len(rows) == 21  # one row per trading day of 2026-06
    for r in rows:
        assert set(r) == HISTORY_KEYS
        assert r["ticker"] == "2330"
        assert r["change_pct"] is None  # history change column intentionally dropped


def test_parse_twse_history_known_day(twse_history_fixture):
    # 2026-06-03 (ROC 115/06/03): close 2,425.00; volume 29,219,904 shares.
    rows = twse_history.parse(twse_history_fixture, "2330")
    r = next(x for x in rows if x["date"] == "2026-06-03")
    assert r["close"] == 2425.0  # matches fixture raw '2,425.00'
    assert r["open"] == 2425.0
    assert r["high"] == 2440.0
    assert r["low"] == 2410.0
    assert r["volume"] == 29_219_904  # 成交股數 is already in shares


def test_twse_history_nodata_returns_empty(twse_history_nodata_fixture):
    # Future month: stat != "OK" -> [] (no raise).
    assert twse_history.parse(twse_history_nodata_fixture, "2330") == []


def test_twse_history_field_drift_raises(twse_history_fixture):
    # Missing a price/date column is structural drift -> raise, never silent [].
    drifted = {
        **twse_history_fixture,
        "fields": ["改名日期", *twse_history_fixture["fields"][1:]],
    }
    with pytest.raises(SourceFetchError) as excinfo:
        twse_history.parse(drifted, "2330")
    assert "TWSE" in str(excinfo.value)


def test_twse_history_fetch_builds_url(monkeypatch):
    captured = {}

    def fake_get_json_dict(url, *, source):
        captured["url"] = url
        captured["source"] = source
        return {"stat": "OK", "fields": [], "data": []}

    monkeypatch.setattr(_common, "get_json_dict", fake_get_json_dict)
    monkeypatch.setattr(twse_history.time, "sleep", lambda _s: None)  # 不真睡
    twse_history.fetch("2330", 2026, 6)
    assert "date=20260601" in captured["url"]
    assert "stockNo=2330" in captured["url"]
    assert captured["source"] == "TWSE-History"


def test_parse_tpex_history_shape(tpex_history_fixture):
    rows = tpex_history.parse(tpex_history_fixture, "3081")
    assert len(rows) == 21
    for r in rows:
        assert set(r) == HISTORY_KEYS
        assert r["ticker"] == "3081"
        assert r["change_pct"] is None


def test_parse_tpex_history_known_day(tpex_history_fixture):
    # 2026-06-01 (ROC 115/06/01): close 2,685.00; volume 1,639 lots -> shares.
    rows = tpex_history.parse(tpex_history_fixture, "3081")
    r = next(x for x in rows if x["date"] == "2026-06-01")
    assert r["close"] == 2685.0  # matches fixture raw '2,685.00'
    assert r["open"] == 2620.0
    assert r["high"] == 2740.0
    assert r["low"] == 2585.0
    # 成交張數 is in 張 (lots); source flagField='張數'. Normalised to shares (x1000).
    assert r["volume"] == 1_639 * 1000


def test_tpex_history_nodata_returns_empty(tpex_history_nodata_fixture):
    # Future month: stat stays "ok" but tables[0].data empty -> [] (no raise).
    assert tpex_history.parse(tpex_history_nodata_fixture, "3081") == []


def test_tpex_history_field_drift_raises(tpex_history_fixture):
    table = tpex_history_fixture["tables"][0]
    drifted = {
        **tpex_history_fixture,
        "tables": [{**table, "fields": ["日 期", "成交仟元", *table["fields"][2:]]}],
    }
    with pytest.raises(SourceFetchError) as excinfo:
        tpex_history.parse(drifted, "3081")
    assert "TPEx" in str(excinfo.value)


def test_tpex_history_fetch_builds_url(monkeypatch):
    captured = {}

    def fake_get_json_dict(url, *, source):
        captured["url"] = url
        captured["source"] = source
        return {"stat": "ok", "tables": [{"fields": [], "data": []}]}

    monkeypatch.setattr(_common, "get_json_dict", fake_get_json_dict)
    monkeypatch.setattr(tpex_history.time, "sleep", lambda _s: None)  # 不真睡
    tpex_history.fetch("3081", 2026, 6)
    assert "date=2026/06/01" in captured["url"] or "date=2026%2F06%2F01" in captured["url"]
    assert "code=3081" in captured["url"]
    assert captured["source"] == "TPEx-History"


# --- Yahoo 指數 (v8 chart, 每日焦點指數列) -----------------------------------

YAHOO_KEYS = {"symbol", "name", "price", "change", "change_pct"}


@pytest.fixture
def yahoo_twii_fixture() -> dict:
    return json.loads(
        (FIXTURES_DIR / "yahoo_twii.json").read_text(encoding="utf-8")
    )


@pytest.fixture
def yahoo_nvda_fixture() -> dict:
    return json.loads(
        (FIXTURES_DIR / "yahoo_nvda.json").read_text(encoding="utf-8")
    )


@pytest.fixture
def yahoo_error_fixture() -> dict:
    return json.loads(
        (FIXTURES_DIR / "yahoo_error.json").read_text(encoding="utf-8")
    )


def test_yahoo_symbols_constant():
    # 7 tracked symbols with the Chinese display names (not Yahoo's English).
    assert yahoo_indices.SYMBOLS == {
        "^TWII": "加權指數",
        "^SOX": "費城半導體",
        "^GSPC": "S&P 500",
        "TSM": "台積電 ADR",
        "NVDA": "輝達 NVDA",
        "^N225": "日經 225",
        "^VIX": "VIX 恐慌",
    }


def test_parse_yahoo_twii(yahoo_twii_fixture):
    # Recorded 2026-07-11: price=45354.61, chartPreviousClose=45734.41.
    r = yahoo_indices.parse(yahoo_twii_fixture, "^TWII")
    assert set(r) == YAHOO_KEYS
    assert r["symbol"] == "^TWII"
    assert r["name"] == "加權指數"  # from SYMBOLS, not Yahoo's English shortName
    assert r["price"] == 45354.61
    assert r["change"] == pytest.approx(-379.8)
    assert r["change_pct"] == pytest.approx(-0.83)


def test_parse_yahoo_nvda_change_pct_matches_manual(yahoo_nvda_fixture):
    # Manual: 210.96 - 202.78 = 8.18; 8.18 / 202.78 * 100 = 4.0339... -> 4.03.
    r = yahoo_indices.parse(yahoo_nvda_fixture, "NVDA")
    assert r["price"] == 210.96
    assert r["change"] == pytest.approx(round(210.96 - 202.78, 2))
    assert r["change_pct"] == pytest.approx(round((210.96 - 202.78) / 202.78 * 100, 2))


def test_parse_yahoo_error_raises(yahoo_error_fixture):
    # Recorded INVALID_XYZ response: chart.error={'code':'Not Found', ...}.
    with pytest.raises(SourceFetchError) as excinfo:
        yahoo_indices.parse(yahoo_error_fixture, "INVALID_XYZ")
    assert "Yahoo" in str(excinfo.value)


@pytest.mark.parametrize(
    "raw",
    [
        {"chart": {"result": [], "error": None}},  # empty result list
        {"chart": {"result": None, "error": None}},  # null result
        {"chart": {}},  # missing both
        {},  # no chart at all
    ],
)
def test_parse_yahoo_empty_result_raises(raw):
    with pytest.raises(SourceFetchError):
        yahoo_indices.parse(raw, "^TWII")


def _yahoo_raw(price, prev):
    meta = {}
    if price is not None:
        meta["regularMarketPrice"] = price
    if prev is not None:
        meta["chartPreviousClose"] = prev
    return {"chart": {"result": [{"meta": meta}], "error": None}}


def test_parse_yahoo_zero_or_missing_prev_close():
    # prev == 0 (division guard) or missing -> change & change_pct both None.
    for raw in (_yahoo_raw(100.0, 0), _yahoo_raw(100.0, None)):
        r = yahoo_indices.parse(raw, "^TWII")
        assert r["price"] == 100.0
        assert r["change"] is None
        assert r["change_pct"] is None


def test_parse_yahoo_missing_price():
    r = yahoo_indices.parse(_yahoo_raw(None, 200.0), "NVDA")
    assert r["price"] is None
    assert r["change"] is None
    assert r["change_pct"] is None


class _FakeCffiResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def test_yahoo_fetch_uses_chrome_impersonation(monkeypatch, yahoo_twii_fixture):
    captured = {}

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return _FakeCffiResponse(payload=yahoo_twii_fixture)

    monkeypatch.setattr(yahoo_indices.cffi_requests, "get", fake_get)
    monkeypatch.setattr(yahoo_indices.time, "sleep", lambda _s: None)  # 不真睡
    raw = yahoo_indices.fetch("^TWII")
    assert raw == yahoo_twii_fixture
    assert "/v8/finance/chart/^TWII" in captured["url"]
    assert "interval=1d" in captured["url"] and "range=1d" in captured["url"]
    assert captured["kwargs"]["impersonate"] == "chrome"


def test_yahoo_fetch_sleeps_rate_limit(monkeypatch, yahoo_twii_fixture):
    slept = []
    monkeypatch.setattr(
        yahoo_indices.cffi_requests,
        "get",
        lambda url, **kw: _FakeCffiResponse(payload=yahoo_twii_fixture),
    )
    monkeypatch.setattr(yahoo_indices.time, "sleep", slept.append)
    yahoo_indices.fetch("NVDA")
    assert slept == [yahoo_indices._RATE_LIMIT_SECONDS] and slept == [0.5]


def test_yahoo_fetch_wraps_non_200(monkeypatch):
    # e.g. the TLS-fingerprint 429 or the 404 an unknown symbol returns.
    monkeypatch.setattr(
        yahoo_indices.cffi_requests,
        "get",
        lambda url, **kw: _FakeCffiResponse(status_code=429, text="Too Many Requests"),
    )
    monkeypatch.setattr(yahoo_indices.time, "sleep", lambda _s: None)
    with pytest.raises(SourceFetchError) as excinfo:
        yahoo_indices.fetch("^TWII")
    assert excinfo.value.status_code == 429
    assert "Yahoo" in str(excinfo.value)


def test_yahoo_fetch_wraps_invalid_json(monkeypatch):
    monkeypatch.setattr(
        yahoo_indices.cffi_requests,
        "get",
        lambda url, **kw: _FakeCffiResponse(payload=None, text="<html>block</html>"),
    )
    monkeypatch.setattr(yahoo_indices.time, "sleep", lambda _s: None)
    with pytest.raises(SourceFetchError) as excinfo:
        yahoo_indices.fetch("^TWII")
    assert excinfo.value.status_code == 200


def test_yahoo_fetch_wraps_connection_error(monkeypatch):
    def boom(url, **kw):
        raise yahoo_indices.cffi_requests.exceptions.RequestException("dns fail")

    monkeypatch.setattr(yahoo_indices.cffi_requests, "get", boom)
    monkeypatch.setattr(yahoo_indices.time, "sleep", lambda _s: None)
    with pytest.raises(SourceFetchError) as excinfo:
        yahoo_indices.fetch("^TWII")
    assert "Yahoo" in str(excinfo.value)


def test_yahoo_fetch_wraps_non_dict_json(monkeypatch):
    # 200 whose JSON is a list, not the expected {chart: ...} dict (M2).
    monkeypatch.setattr(
        yahoo_indices.cffi_requests,
        "get",
        lambda url, **kw: _FakeCffiResponse(payload=[1, 2, 3]),
    )
    monkeypatch.setattr(yahoo_indices.time, "sleep", lambda _s: None)
    with pytest.raises(SourceFetchError) as excinfo:
        yahoo_indices.fetch("^TWII")
    assert excinfo.value.status_code == 200
    assert "Yahoo" in str(excinfo.value)


# --- 市場統計 (三大法人買賣金額 BFI82U + 信用交易 MI_MARGN) -------------------

MARKET_FLOW_KEYS = {"unit", "buy", "sell", "net", "date"}
MARGIN_KEYS = {"item", "buy", "sell", "prev_balance", "today_balance", "date"}


@pytest.fixture
def bfi82u_fixture() -> dict:
    return json.loads(
        (FIXTURES_DIR / "twse_bfi82u.json").read_text(encoding="utf-8")
    )


@pytest.fixture
def bfi82u_holiday_fixture() -> dict:
    return json.loads(
        (FIXTURES_DIR / "twse_bfi82u_holiday.json").read_text(encoding="utf-8")
    )


@pytest.fixture
def margin_fixture() -> dict:
    return json.loads(
        (FIXTURES_DIR / "twse_margin.json").read_text(encoding="utf-8")
    )


@pytest.fixture
def margin_holiday_fixture() -> dict:
    return json.loads(
        (FIXTURES_DIR / "twse_margin_holiday.json").read_text(encoding="utf-8")
    )


def test_parse_bfi82u(bfi82u_fixture):
    rows = twse_bfi82u.parse(bfi82u_fixture, "2026-07-09")
    assert len(rows) == 6  # 5 身份別 + 合計
    for r in rows:
        assert set(r) == MARKET_FLOW_KEYS
        assert r["date"] == "2026-07-09"
    # 身份別 names kept verbatim (original labels, not rewritten).
    r = next(x for x in rows if x["unit"] == "外資及陸資(不含外資自營商)")
    assert r["buy"] == 367_858_937_128  # amounts in 元, commas parsed
    assert r["sell"] == 415_111_753_557
    assert r["net"] == -47_252_816_429


def test_bfi82u_buy_minus_sell_equals_net(bfi82u_fixture):
    # 驗算 buy − sell == net on the 自營商(自行買賣) row (in 元).
    rows = twse_bfi82u.parse(bfi82u_fixture, "2026-07-09")
    r = next(x for x in rows if x["unit"] == "自營商(自行買賣)")
    assert r["buy"] == 9_494_954_521
    assert r["sell"] == 11_531_142_442
    assert r["buy"] - r["sell"] == r["net"] == -2_036_187_921


def test_bfi82u_holiday_returns_empty(bfi82u_holiday_fixture):
    # Non-trading day: stat != "OK" (bare {stat, hints}) -> [] (no raise).
    assert twse_bfi82u.parse(bfi82u_holiday_fixture, "2026-07-12") == []


def test_bfi82u_field_drift_raises(bfi82u_fixture):
    # A dropped/renamed amount column is structural drift -> raise, never [].
    drifted = {
        **bfi82u_fixture,
        "fields": ["單位名稱", "改名買進", *bfi82u_fixture["fields"][2:]],
    }
    with pytest.raises(SourceFetchError) as excinfo:
        twse_bfi82u.parse(drifted, "2026-07-09")
    assert "TWSE-BFI82U" in str(excinfo.value)


def test_bfi82u_fetch_builds_yyyymmdd_url(monkeypatch):
    captured = {}

    def fake_get_json_dict(url, *, source):
        captured["url"] = url
        captured["source"] = source
        return {"stat": "OK", "fields": [], "data": []}

    monkeypatch.setattr(_common, "get_json_dict", fake_get_json_dict)
    twse_bfi82u.fetch("2026-07-09")
    assert "dayDate=20260709" in captured["url"]
    assert captured["source"] == "TWSE-BFI82U"


def test_parse_margin(margin_fixture):
    rows = twse_margin.parse(margin_fixture, "2026-07-09")
    assert len(rows) == 3  # 融資(交易單位) / 融券(交易單位) / 融資金額(仟元)
    for r in rows:
        assert set(r) == MARGIN_KEYS
        assert r["date"] == "2026-07-09"
    # item labels kept verbatim; raw 張/仟元 values kept as-is (no conversion).
    r = next(x for x in rows if x["item"] == "融資金額(仟元)")
    assert r["buy"] == 31_178_841
    assert r["sell"] == 24_806_032
    assert r["prev_balance"] == 613_815_722
    assert r["today_balance"] == 619_648_244


def test_margin_parses_credit_stats_table(margin_fixture):
    # MS is a multi-table response: tables[0] is 信用交易統計, tables[1] is {}.
    # Verify we picked the right (non-empty) table.
    rows = twse_margin.parse(margin_fixture, "2026-07-09")
    r = next(x for x in rows if x["item"] == "融資(交易單位)")
    assert r["buy"] == 372_813  # 張 (lots), kept as-is
    assert r["today_balance"] == 9_614_955


def test_margin_holiday_returns_empty(margin_holiday_fixture):
    # Non-trading day: bare {stat} with no tables key -> [] (no raise).
    assert twse_margin.parse(margin_holiday_fixture, "2026-07-12") == []


def test_margin_empty_tables_returns_empty(margin_fixture):
    # stat OK but tables[0] has no data rows -> [] (holiday semantics, no raise).
    table = margin_fixture["tables"][0]
    empty = {**margin_fixture, "tables": [{**table, "data": []}, {}]}
    assert twse_margin.parse(empty, "2026-07-09") == []


def test_margin_field_drift_raises(margin_fixture):
    # A dropped/renamed column in the credit table is drift -> raise, never [].
    table = margin_fixture["tables"][0]
    drifted = {
        **margin_fixture,
        "tables": [{**table, "fields": ["項目", "改名買進", *table["fields"][2:]]}, {}],
    }
    with pytest.raises(SourceFetchError) as excinfo:
        twse_margin.parse(drifted, "2026-07-09")
    assert "TWSE-Margin" in str(excinfo.value)


def test_margin_fetch_builds_yyyymmdd_url(monkeypatch):
    captured = {}

    def fake_get_json_dict(url, *, source):
        captured["url"] = url
        captured["source"] = source
        return {"stat": "OK", "tables": [{"fields": [], "data": []}]}

    monkeypatch.setattr(_common, "get_json_dict", fake_get_json_dict)
    twse_margin.fetch("2026-07-09")
    assert "date=20260709" in captured["url"]
    assert "selectType=MS" in captured["url"]
    assert captured["source"] == "TWSE-Margin"


# --- MOPS 重大訊息 (公開資訊觀測站) -----------------------------------------

MOPS_KEYS = {"ticker", "name", "title", "published_at", "category"}


@pytest.fixture
def mops_listed_fixture() -> list[dict]:
    return json.loads(
        (FIXTURES_DIR / "mops_listed.json").read_text(encoding="utf-8")
    )


@pytest.fixture
def mops_otc_fixture() -> list[dict]:
    return json.loads((FIXTURES_DIR / "mops_otc.json").read_text(encoding="utf-8"))


def test_parse_mops_listed(mops_listed_fixture):
    rows = mops.parse(mops_listed_fixture)
    assert rows and all(set(r) == MOPS_KEYS for r in rows)
    r = rows[0]
    assert r["ticker"] == "1721" and r["name"] == "三晃"
    assert isinstance(r["published_at"], datetime.datetime)


def test_parse_mops_otc_english_keys(mops_otc_fixture):
    # OTC feed labels ticker/name as SecuritiesCompanyCode/CompanyName —
    # parse resolves them via candidate keys just like the 上市 中文 keys.
    rows = mops.parse(mops_otc_fixture)
    assert len(rows) == len(mops_otc_fixture)
    assert rows[0]["ticker"] == "4530" and rows[0]["name"] == "宏易"


def test_mops_published_at_taipei_to_naive_utc():
    # ROC 1150711 19:00:00 (Taipei) -> naive UTC 2026-07-11 11:00:00 (-8h).
    row = {"公司代號": "2330", "公司名稱": "台積電", "主旨 ": "測試",
           "發言日期": "1150711", "發言時間": "190000"}
    r = mops.parse([row])[0]
    assert r["published_at"] == datetime.datetime(2026, 7, 11, 11, 0, 0)
    assert r["published_at"].tzinfo is None


def test_mops_parses_packed_time_with_stripped_zero(mops_listed_fixture):
    # Feed packs 發言時間 as "70003" (07:00:03), leading zero stripped.
    # 07:00:03 Taipei -> previous-day 23:00:03 UTC.
    r = mops.parse(mops_listed_fixture)[0]
    assert r["published_at"] == datetime.datetime(2026, 7, 10, 23, 0, 3)


def test_mops_skips_rows_missing_date_or_time():
    rows = mops.parse(
        [
            {"公司代號": "1", "主旨 ": "無時間", "發言日期": "1150711", "發言時間": ""},
            {"公司代號": "2", "主旨 ": "無日期", "發言日期": "", "發言時間": "190000"},
            {"公司代號": "3", "主旨 ": "好", "發言日期": "1150711", "發言時間": "190000"},
        ]
    )
    assert [r["ticker"] for r in rows] == ["3"]


@pytest.mark.parametrize(
    "title,expected",
    [
        ("澄清媒體報導本公司相關事宜", "澄清回應"),
        ("公告本公司自結損益", "自結"),
        ("公告本公司財務報告更正", "財務數據"),
        ("公告本公司第二季財報", "財務數據"),
        ("公告董事會決議召開股東會", "公司治理"),
        ("代子公司公告取得不動產", "重大事件"),
        # Priority conflict: 澄清 wins over 財報 (specific rule first).
        ("澄清媒體報導財報疑慮", "澄清回應"),
    ],
)
def test_mops_classify(title, expected):
    assert mops.classify(title) == expected


def test_mops_missing_ticker_column_raises():
    with pytest.raises(SourceFetchError) as excinfo:
        mops.parse([{"主旨 ": "x", "發言日期": "1150711", "發言時間": "190000"}])
    assert "MOPS" in str(excinfo.value)


def test_mops_empty_response_returns_empty():
    assert mops.parse([]) == []


def test_mops_fetch_listed_url(monkeypatch):
    captured = {}

    def fake_get_json(url, *, source):
        captured.update(url=url, source=source)
        return []

    monkeypatch.setattr(_common, "get_json", fake_get_json)
    mops.fetch_listed()
    assert captured["url"] == mops.LISTED_URL
    assert "上市" in captured["source"]


def test_mops_fetch_otc_url(monkeypatch):
    captured = {}

    def fake_get_json(url, *, source):
        captured.update(url=url, source=source)
        return []

    monkeypatch.setattr(_common, "get_json", fake_get_json)
    mops.fetch_otc()
    assert captured["url"] == mops.OTC_URL
    assert "上櫃" in captured["source"]


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("235959", (23, 59, 59)),  # 上界合法：23:59:59
        ("000000", (0, 0, 0)),  # 下界合法：00:00:00
        ("256060", None),  # 時/分/秒皆越界（25:60:60）→ None
        ("1234567", None),  # 七位數（zfill 後仍 != 6 位）→ None
    ],
)
def test_mops_parse_time_boundaries(raw, expected):
    assert mops._parse_time(raw) == expected


# --- 月營收 (每月營業收入, t187ap05) ----------------------------------------

REVENUE_KEYS = {"ticker", "month", "revenue", "yoy"}


@pytest.fixture
def revenue_listed_fixture() -> list[dict]:
    return json.loads(
        (FIXTURES_DIR / "revenue_listed.json").read_text(encoding="utf-8")
    )


@pytest.fixture
def revenue_otc_fixture() -> list[dict]:
    return json.loads(
        (FIXTURES_DIR / "revenue_otc.json").read_text(encoding="utf-8")
    )


def test_parse_revenue_listed(revenue_listed_fixture):
    rows = twse_revenue.parse(revenue_listed_fixture)
    assert len(rows) == len(revenue_listed_fixture)
    assert all(set(r) == REVENUE_KEYS for r in rows)
    r = rows[0]  # 1101 台泥, 資料年月 11506
    assert r["ticker"] == "1101"
    assert r["month"] == "2026-06"
    # 營業收入-當月營收 kept verbatim in 千元 (no scaling): 13,382,706 千元.
    assert r["revenue"] == 13382706
    assert isinstance(r["revenue"], int)
    assert r["yoy"] == pytest.approx(32.39878166305348)


def test_parse_revenue_otc_shares_listed_schema(revenue_otc_fixture):
    # 上櫃 feed uses the identical 中文 schema; tpex_revenue reuses the 上市 parser.
    rows = tpex_revenue.parse(revenue_otc_fixture)
    assert len(rows) == len(revenue_otc_fixture)
    assert all(set(r) == REVENUE_KEYS for r in rows)
    # 3081 聯亞 is the recorded known-ticker row.
    row_3081 = next(r for r in rows if r["ticker"] == "3081")
    assert row_3081["month"] == "2026-06"
    assert row_3081["revenue"] == 420507
    assert row_3081["yoy"] == pytest.approx(128.13717299074446)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("11506", "2026-06"),  # packed 民國 115 年 06 月
        ("115/06", "2026-06"),  # slash form
        ("9912", "2010-12"),  # 4-digit packed (民國 99 年 12 月)
        ("11513", None),  # month 13 越界 → None
        ("", None),  # blank → None
        ("-", None),  # 佔位 → None
        ("115", None),  # too short → None
        (None, None),  # missing → None
    ],
)
def test_revenue_roc_ym_to_month(raw, expected):
    assert twse_revenue.roc_ym_to_month(raw) == expected


def test_revenue_tolerates_blank_and_dash():
    rows = twse_revenue.parse(
        [
            {
                "公司代號": "9999",
                "資料年月": "11506",
                "營業收入-當月營收": "-",
                "營業收入-去年同月增減(%)": "",
            }
        ]
    )
    assert rows == [
        {"ticker": "9999", "month": "2026-06", "revenue": None, "yoy": None}
    ]


def test_revenue_english_key_fallback():
    # Defensive candidate keys: an all-English row still parses.
    rows = twse_revenue.parse(
        [{"Code": "2454", "DataYearMonth": "11506", "Revenue": "58011756", "YoY": "2.8"}]
    )
    assert rows == [
        {"ticker": "2454", "month": "2026-06", "revenue": 58011756, "yoy": 2.8}
    ]


def test_revenue_missing_ticker_column_raises():
    with pytest.raises(SourceFetchError) as excinfo:
        twse_revenue.parse([{"資料年月": "11506", "營業收入-當月營收": "100"}])
    assert "月營收" in str(excinfo.value)


def test_revenue_empty_response_returns_empty():
    assert twse_revenue.parse([]) == []
    assert tpex_revenue.parse([]) == []


def test_revenue_fetch_listed_url(monkeypatch):
    captured = {}

    def fake_get_json(url, *, source):
        captured.update(url=url, source=source)
        return []

    monkeypatch.setattr(_common, "get_json", fake_get_json)
    twse_revenue.fetch()
    assert captured["url"] == twse_revenue.LISTED_URL
    assert "上市" in captured["source"]


def test_revenue_fetch_otc_url(monkeypatch):
    captured = {}

    def fake_get_json(url, *, source):
        captured.update(url=url, source=source)
        return []

    monkeypatch.setattr(_common, "get_json", fake_get_json)
    tpex_revenue.fetch()
    assert captured["url"] == tpex_revenue.OTC_URL
    assert "上櫃" in captured["source"]


# --- 本益比/殖利率/股價淨值比 (PER, BWIBBU_ALL + peratio_analysis) -----------

PER_KEYS = {"ticker", "date", "per", "pbr", "dividend_yield"}

# The whole-market snapshots carry no session date the caller can rely on being
# present, so parse() takes the Taipei trading date the job passes in; it is used
# only as a fallback when a row lacks its own parseable Date column.
CALLER_DATE = "2026-07-09"


@pytest.fixture
def bwibbu_all_fixture() -> list[dict]:
    return json.loads(
        (FIXTURES_DIR / "twse_bwibbu_all.json").read_text(encoding="utf-8")
    )


@pytest.fixture
def tpex_peratio_fixture() -> list[dict]:
    return json.loads(
        (FIXTURES_DIR / "tpex_peratio.json").read_text(encoding="utf-8")
    )


@pytest.fixture
def bwibbu_history_fixture() -> dict:
    return json.loads(
        (FIXTURES_DIR / "twse_bwibbu_history.json").read_text(encoding="utf-8")
    )


@pytest.fixture
def bwibbu_history_nodata_fixture() -> dict:
    return json.loads(
        (FIXTURES_DIR / "twse_bwibbu_history_nodata.json").read_text(encoding="utf-8")
    )


def test_parse_twse_per(bwibbu_all_fixture):
    rows = twse_per.parse(bwibbu_all_fixture, CALLER_DATE)
    assert len(rows) == len(bwibbu_all_fixture)
    r = next(x for x in rows if x["ticker"] == "2330")
    assert set(r) == PER_KEYS
    assert r["date"] == "2026-07-09"  # row Date "1150709" -> ISO
    assert r["per"] == pytest.approx(32.47)
    assert r["pbr"] == pytest.approx(10.63)
    assert r["dividend_yield"] == pytest.approx(0.91)


def test_parse_twse_per_blank_ratio_is_none(bwibbu_all_fixture):
    # 1101 (台泥) has an empty PEratio in the real feed -> None (not a crash).
    rows = twse_per.parse(bwibbu_all_fixture, CALLER_DATE)
    r = next(x for x in rows if x["ticker"] == "1101")
    assert r["per"] is None
    assert r["dividend_yield"] == pytest.approx(3.52)


def test_parse_tpex_per_shares_parser(tpex_peratio_fixture):
    # 上櫃 feed uses English keys (PriceEarningRatio/YieldRatio/PriceBookRatio);
    # tpex_per reuses twse_per.parse via candidate keys.
    rows = tpex_per.parse(tpex_peratio_fixture, CALLER_DATE)
    assert len(rows) == len(tpex_peratio_fixture)
    r = next(x for x in rows if x["ticker"] == "3081")
    assert set(r) == PER_KEYS
    assert r["date"] == "2026-07-09"
    assert r["per"] == pytest.approx(263.47)
    assert r["pbr"] == pytest.approx(43.76)
    assert r["dividend_yield"] == pytest.approx(0.20)


def test_per_caller_date_fallback_when_no_date_column():
    # A row without a Date column falls back to the caller-supplied trading date.
    rows = twse_per.parse(
        [{"Code": "2330", "PEratio": "30", "PBratio": "10", "DividendYield": "1.5"}],
        CALLER_DATE,
    )
    assert rows[0]["date"] == CALLER_DATE
    assert rows[0]["per"] == pytest.approx(30.0)


def test_per_blank_or_bad_date_falls_back_to_caller():
    # M1: Date column PRESENT but blank / unparseable -> caller trading date, not
    # a crash and not a None date (distinct from the missing-column case above).
    rows = twse_per.parse(
        [
            {"Date": "", "Code": "2330", "PEratio": "30"},
            {"Date": "not-a-date", "Code": "2454", "PEratio": "20"},
        ],
        CALLER_DATE,
    )
    assert rows[0]["date"] == CALLER_DATE
    assert rows[1]["date"] == CALLER_DATE


def test_per_tolerates_dash_and_blank():
    rows = twse_per.parse(
        [
            {
                "Date": "1150709",
                "Code": "9999",
                "PEratio": "-",
                "PBratio": "",
                "DividendYield": "N/A",
            }
        ],
        CALLER_DATE,
    )
    assert rows[0] == {
        "ticker": "9999",
        "date": "2026-07-09",
        "per": None,
        "pbr": None,
        "dividend_yield": None,
    }


def test_per_missing_ticker_column_raises():
    with pytest.raises(SourceFetchError):
        twse_per.parse([{"Date": "1150709", "PEratio": "30"}], CALLER_DATE)


def test_per_empty_response_returns_empty():
    assert twse_per.parse([], CALLER_DATE) == []
    assert tpex_per.parse([], CALLER_DATE) == []


def test_per_fetch_listed_url(monkeypatch):
    captured = {}

    def fake_get_json(url, *, source):
        captured.update(url=url, source=source)
        return []

    monkeypatch.setattr(_common, "get_json", fake_get_json)
    twse_per.fetch()
    assert captured["url"] == twse_per.LISTED_URL
    assert "上市" in captured["source"]


def test_per_fetch_otc_url(monkeypatch):
    captured = {}

    def fake_get_json(url, *, source):
        captured.update(url=url, source=source)
        return []

    monkeypatch.setattr(_common, "get_json", fake_get_json)
    tpex_per.fetch()
    assert captured["url"] == tpex_per.OTC_URL
    assert "上櫃" in captured["source"]


def test_parse_twse_per_history(bwibbu_history_fixture):
    rows = twse_per_history.parse(bwibbu_history_fixture, "2330")
    assert len(rows) == len(bwibbu_history_fixture["data"])
    r0 = rows[0]
    assert set(r0) == PER_KEYS
    assert r0["ticker"] == "2330"
    assert r0["date"] == "2026-06-01"  # "115年06月01日" -> ISO
    assert r0["per"] == pytest.approx(31.66)
    assert r0["pbr"] == pytest.approx(10.37)
    assert r0["dividend_yield"] == pytest.approx(0.93)
    # dates are monotonically increasing ISO strings across the month
    assert rows[-1]["date"] > rows[0]["date"]


def test_twse_per_history_nodata_returns_empty(bwibbu_history_nodata_fixture):
    assert twse_per_history.parse(bwibbu_history_nodata_fixture, "2330") == []


def test_twse_per_history_missing_column_raises():
    # Drift guard: an expected header disappearing must not silently empty-parse.
    raw = {
        "stat": "OK",
        "fields": ["日期", "股利年度", "本益比", "財報年/季"],  # 殖利率/股價淨值比 gone
        "data": [["115年06月01日", 114, "31.66", "115/1"]],
    }
    with pytest.raises(SourceFetchError):
        twse_per_history.parse(raw, "2330")


def test_twse_per_history_fetch_rate_limited(monkeypatch):
    captured = {}

    def fake_get_json_dict(url, *, source):
        captured.update(url=url, source=source)
        return {"stat": "OK", "fields": [], "data": []}

    slept = {}
    monkeypatch.setattr(_common, "get_json_dict", fake_get_json_dict)
    monkeypatch.setattr(twse_per_history.time, "sleep", lambda s: slept.update(s=s))
    twse_per_history.fetch("2330", 2026, 6)
    assert "date=20260601" in captured["url"]
    assert "stockNo=2330" in captured["url"]
    assert slept["s"] > 0  # politeness pacing applied


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("115年06月01日", "2026-06-01"),
        ("115年6月1日", "2026-06-01"),
        ("", None),
        ("garbage", None),
        (None, None),
    ],
)
def test_roc_cn_to_iso(raw, expected):
    assert _common.roc_cn_to_iso(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("20260703", "2026-07-03"),
        ("20261231", "2026-12-31"),
        ("2026070", None),  # 7 digits
        ("2026-07-03", None),  # not bare digits
        ("20261331", None),  # month 13
        ("", None),
        (None, None),
    ],
)
def test_yyyymmdd_to_iso(raw, expected):
    assert _common.yyyymmdd_to_iso(raw) == expected


# --- 集保股權分散 (TDCC, id=1-5, streamed CSV) -------------------------------
# Fixture = the real recorded header + all 17 級距 rows for the 17 seeded tickers
# + 3 noise tickers (2317/0050/6505) as drift-representative rows. read_text with
# utf-8-sig strips the BOM the live feed carries (as fetch() does).

TDCC_KEYS = {"ticker", "week", "ratio_400up", "holder_count"}
TDCC_WANTED = {
    "2330", "3443", "3081", "3450", "4979", "2426", "6442", "3163", "2489",
    "3711", "4977", "6789", "3363", "6223", "6515", "3289", "6451",
}


@pytest.fixture
def tdcc_fixture() -> str:
    return (FIXTURES_DIR / "tdcc_holders.csv").read_text(encoding="utf-8-sig")


def test_parse_tdcc_shape(tdcc_fixture):
    rows = tdcc_holders.parse(tdcc_fixture, TDCC_WANTED)
    # One aggregated row per wanted ticker (single-week snapshot); noise excluded.
    assert len(rows) == len(TDCC_WANTED)
    assert {r["ticker"] for r in rows} == TDCC_WANTED
    for r in rows:
        assert set(r) == TDCC_KEYS
        assert r["week"] == "2026-07-03"
        assert isinstance(r["ratio_400up"], float)
        assert isinstance(r["holder_count"], int)


def test_tdcc_ratio_400up_matches_manual(tdcc_fixture):
    # 2330 級距 12–15 占比: 1.05 + 0.94 + 0.73 + 85.09 = 87.81.
    rows = tdcc_holders.parse(tdcc_fixture, {"2330"})
    assert len(rows) == 1
    r = rows[0]
    assert r["ratio_400up"] == pytest.approx(87.81)
    # holder_count = Σ 人數 級距 1–15 = 合計(級17)人數 when 差異數調整=0.
    assert r["holder_count"] == 2898020


def test_tdcc_level_ratios_sum_to_about_100(tdcc_fixture):
    # 驗算: a security's 15 真實級距 占比合計 ≈ 100 (±0.5, per-level 2dp rounding).
    # ratio_400up is a subset of this whole, so the invariant anchors it.
    import csv
    import io

    reader = csv.reader(io.StringIO(tdcc_fixture))
    next(reader)
    total = 0.0
    for parts in reader:
        if parts[1].strip() == "2330" and parts[2].strip() in {str(i) for i in range(1, 16)}:
            total += float(parts[5])
    assert total == pytest.approx(100.0, abs=0.5)


def test_tdcc_excludes_adjustment_and_total_levels():
    # 級距 16 (差異數調整) and 17 (合計) must never enter holder_count/ratio —
    # counting 17 would double the holders, counting its 100% would blow ratio.
    csv_text = (
        "資料日期,證券代號,持股分級,人數,股數,占集保庫存數比例%\n"
        "20260703,9999,1,10,100,40.00\n"
        "20260703,9999,15,5,900,60.00\n"
        "20260703,9999,16,0,0,0.00\n"  # 差異數調整
        "20260703,9999,17,15,1000,100.00\n"  # 合計
    )
    rows = tdcc_holders.parse(csv_text, {"9999"})
    assert rows[0]["holder_count"] == 15  # 10 + 5, not 30
    assert rows[0]["ratio_400up"] == pytest.approx(60.00)  # 級距 15 only


def test_tdcc_strips_space_padded_ticker(tdcc_fixture):
    # 證券代號 is space-padded to 6 chars in the feed ('2330  '); wanted matching
    # and the emitted ticker must both be stripped.
    rows = tdcc_holders.parse(tdcc_fixture, {"0050"})  # noise ETF row present
    assert len(rows) == 1
    assert rows[0]["ticker"] == "0050"


def test_tdcc_wanted_filter_excludes_others(tdcc_fixture):
    rows = tdcc_holders.parse(tdcc_fixture, {"2330"})
    assert [r["ticker"] for r in rows] == ["2330"]


def test_tdcc_empty_wanted_returns_empty(tdcc_fixture):
    assert tdcc_holders.parse(tdcc_fixture, set()) == []


def test_tdcc_holder_count_none_when_all_blank():
    csv_text = (
        "資料日期,證券代號,持股分級,人數,股數,占集保庫存數比例%\n"
        "20260703,8888,1,,, \n"
        "20260703,8888,12,,,50.00\n"
    )
    rows = tdcc_holders.parse(csv_text, {"8888"})
    assert rows[0]["holder_count"] is None
    assert rows[0]["ratio_400up"] == pytest.approx(50.00)


def test_tdcc_bad_header_raises():
    # Missing 持股分級 + 占集保庫存數比例% -> structural drift, not empty parse.
    with pytest.raises(SourceFetchError):
        tdcc_holders.parse(
            "資料日期,證券代號,人數\n20260703,2330,5\n", {"2330"}
        )


def test_tdcc_empty_input_raises():
    with pytest.raises(SourceFetchError):
        tdcc_holders.parse("", {"2330"})


def test_tdcc_skips_row_with_unparseable_date():
    # 資料日期 無法解析（非 8 位 YYYYMMDD）→ 該列 skip，不產出 (ticker, None) 鍵。
    # 只要另有想要的列帶有效日期，整體不 raise。
    csv_text = (
        "資料日期,證券代號,持股分級,人數,股數,占集保庫存數比例%\n"
        "BADDATE,2330,15,5,900,60.00\n"
        "20260703,3081,15,3,100,50.00\n"
    )
    rows = tdcc_holders.parse(csv_text, {"2330", "3081"})
    # 2330 的唯一列日期壞掉被跳過 → 不產出；3081 正常。
    assert [r["ticker"] for r in rows] == ["3081"]
    assert rows[0]["week"] == "2026-07-03"


def test_tdcc_all_wanted_rows_unparseable_date_raises():
    # 想要的列全部日期無法解析 → 結構漂移，raise 而非回空（與 bad header 同philosophy）。
    csv_text = (
        "資料日期,證券代號,持股分級,人數,股數,占集保庫存數比例%\n"
        "BADDATE,2330,15,5,900,60.00\n"
    )
    with pytest.raises(SourceFetchError):
        tdcc_holders.parse(csv_text, {"2330"})


def test_tdcc_fetch_wraps_decode_error(monkeypatch):
    # 非法位元組 → utf-8-sig decode 失敗須包成 SourceFetchError，不外拋 UnicodeDecodeError。
    bad_bytes = b"\xff\xfe\x00\x01 not valid utf-8"
    response = _FakeStreamResponse(chunks=[bad_bytes])
    monkeypatch.setattr(
        tdcc_holders.httpx, "Client", lambda **kw: _FakeStreamClient(response)
    )
    with pytest.raises(SourceFetchError) as excinfo:
        tdcc_holders.fetch()
    assert "集保" in str(excinfo.value)


class _FakeStreamResponse:
    def __init__(self, *, status_code=200, chunks=()):
        self.status_code = status_code
        self._chunks = chunks

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_bytes(self):
        yield from self._chunks


class _FakeStreamClient:
    def __init__(self, response):
        self._response = response
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def stream(self, method, url, headers=None):
        self.calls.append((method, url, headers))
        return self._response


def test_tdcc_fetch_streams_and_strips_bom(monkeypatch):
    body = (
        "﻿資料日期,證券代號,持股分級,人數,股數,占集保庫存數比例%\r\n"
        "20260703,2330  ,15,1481,22066084295,85.09\r\n"
    ).encode("utf-8")
    response = _FakeStreamResponse(chunks=[body[:20], body[20:]])  # split mid-stream
    client = _FakeStreamClient(response)
    captured = {}

    def fake_client(**kwargs):
        captured["kwargs"] = kwargs
        return client

    monkeypatch.setattr(tdcc_holders.httpx, "Client", fake_client)
    text = tdcc_holders.fetch()
    assert text.startswith("資料日期")  # BOM removed by utf-8-sig
    method, url, headers = client.calls[0]
    assert method == "GET" and url == tdcc_holders.STREAM_URL
    assert "Mozilla" in headers["User-Agent"]  # browser UA
    # end-to-end: parse the streamed text back out
    rows = tdcc_holders.parse(text, {"2330"})
    assert rows[0]["ratio_400up"] == pytest.approx(85.09)


def test_tdcc_fetch_wraps_non_200(monkeypatch):
    response = _FakeStreamResponse(status_code=503, chunks=[])
    monkeypatch.setattr(
        tdcc_holders.httpx, "Client", lambda **kw: _FakeStreamClient(response)
    )
    with pytest.raises(SourceFetchError) as excinfo:
        tdcc_holders.fetch()
    assert excinfo.value.status_code == 503
    assert "集保" in str(excinfo.value)


def test_tdcc_fetch_wraps_connection_error(monkeypatch):
    class _Boom:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def stream(self, *a, **kw):
            raise httpx.ConnectError("dns fail")

    monkeypatch.setattr(tdcc_holders.httpx, "Client", lambda **kw: _Boom())
    with pytest.raises(SourceFetchError) as excinfo:
        tdcc_holders.fetch()
    assert "集保" in str(excinfo.value)
