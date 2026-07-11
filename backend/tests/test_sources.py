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
    tpex_institutional,
    twse,
    twse_t86,
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
