"""Tests for TWSE/TPEx source clients — parsing only, no network.

Fixtures under tests/fixtures/ are real API responses recorded once via
scripts/record_fixtures.py (first 5 rows + a known ticker).
"""

import json
from pathlib import Path

import httpx
import pytest

from app.pipeline.sources import (
    _common,
    tpex,
    tpex_history,
    tpex_institutional,
    twse,
    twse_bfi82u,
    twse_history,
    twse_margin,
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
