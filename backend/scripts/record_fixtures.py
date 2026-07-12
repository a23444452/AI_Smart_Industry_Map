"""Record real TWSE/TPEx OpenAPI responses into test fixtures.

Fetches the two public endpoints and stores a small representative slice
(first 5 rows + the row containing a known ticker) into the fixtures dir,
preserving the raw field names exactly as returned by the source.

Run once, manually, to (re)generate fixtures:

    uv run python scripts/record_fixtures.py
"""

from __future__ import annotations

import json
import ssl
import time
from pathlib import Path

import httpx

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

# --- Yahoo Finance 指數 (v8 chart) ------------------------------------------
# The public chart endpoint returns a nested object
# {chart:{result:[{meta:{...}, timestamp, indicators}], error}} — one meta block
# per symbol with regularMarketPrice / chartPreviousClose. Yahoo fingerprints
# the TLS handshake and 429s non-browser clients — httpx/curl are blocked even
# with a browser User-Agent header — so this recorder uses curl_cffi with
# impersonate="chrome" (the yfinance community's standard workaround). We sleep
# 0.5s between requests to stay polite, record ^TWII + NVDA as the happy-path
# fixtures, and an INVALID_XYZ symbol whose response carries a non-null
# chart.error.
YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1d"
YAHOO_SYMBOLS = ["^TWII", "^SOX", "^GSPC", "TSM", "NVDA", "^N225", "^VIX"]
YAHOO_RATE_LIMIT_SECONDS = 0.5

TWSE_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TPEX_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"

# MOPS 重大訊息 (公開資訊觀測站, t187ap04). Both markets serve a bare list[dict]
# of *today's* announcements — no date parameter. The two feeds disagree on
# field names, so parse() resolves each value across candidate keys:
#   listed (TWSE): 公司代號 / 公司名稱 / "主旨 " (trailing space) / 發言日期 / 發言時間
#   OTC   (TPEx):  SecuritiesCompanyCode / CompanyName / 主旨 / 發言日期 / 發言時間
# 發言時間 is packed HHMMSS with the leading zero stripped ("70003" = 07:00:03).
# Counts vary by day (only same-day filings appear); we record the first 5 rows
# of each and print the full same-day count for traceability.
MOPS_LISTED_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap04_L"
MOPS_OTC_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap04_O"

# 月營收 (t187ap05). Both markets serve a bare list[dict] of the *latest*
# reported month (no date parameter). Unlike MOPS 重大訊息, both feeds use the
# SAME 中文 field names — 資料年月 (ROC packed "11506" = 2026-06), 公司代號,
# 營業收入-當月營收 (千元), 營業收入-去年同月增減(%) (YoY %). We record the first
# 5 rows plus a known ticker per market. 2330 (台積電) does not file through this
# monthly-revenue feed, so the 上市 fixture substitutes 2454 (聯發科, 半導體業);
# the 上櫃 feed carries 3081 (聯亞).
REVENUE_LISTED_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
REVENUE_OTC_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O"
REVENUE_LISTED_TICKER = "2454"  # 2330 absent from this feed; use 聯發科 instead
REVENUE_OTC_TICKER = "3081"  # 聯亞 (上櫃)

# Institutional (三大法人) — date-parameterised, table-shaped responses.
# T86 returns a dict {stat, date, fields, data:[row,...]}; TPEx dailyTrade
# returns {stat, tables:[{fields, date, data:[row,...]}]}. Both list rows as
# positional arrays, so a fixture keeps the `fields` header alongside `data`.
# 2026-07-09 (ROC 115/07/09) is the latest trading day the live servers hold;
# 2026-07-10/11 return an empty "no data" response (recorded as the holiday
# fixtures) — the task's suggested 2026-07-10 is not a settled trading day.
INSTI_DATE_ISO = "2026-07-09"
INSTI_DATE_YMD = "20260709"
INSTI_DATE_ROC = "115/07/09"
INSTI_HOLIDAY_YMD = "20260711"
INSTI_HOLIDAY_ROC = "115/07/11"

T86_URL = (
    "https://www.twse.com.tw/rwd/zh/fund/T86"
    "?date={date}&selectType=ALLBUT0999&response=json"
)
TPEX_INSTI_URL = (
    "https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade"
    "?type=Daily&sect=EW&date={date}&response=json"
)

# Per-stock monthly OHLCV history (backfill source). TWSE STOCK_DAY takes an
# AD ``YYYYMM01`` date; TPEx tradingStock takes an AD ``YYYY/MM/DD`` (day fixed
# to 01) date. Both return one row per trading day of that month. 2026-06 is a
# settled month; 2027-01 is in the future, so each source returns its own
# "no data" shape (recorded as the *_nodata fixtures).
HIST_TWSE_TICKER = "2330"  # 台積電 (上市)
HIST_TPEX_TICKER = "3081"  # 聯亞 (上櫃)
HIST_YM = ("2026", "06")
HIST_FUTURE_YM = ("2027", "01")

TWSE_HISTORY_URL = (
    "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"
    "?date={date}&stockNo={ticker}&response=json"
)
TPEX_HISTORY_URL = (
    "https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock"
    "?code={ticker}&date={date}&response=json"
)

# Market-wide statistics (每日焦點市場統計) — date-parameterised (AD YYYYMMDD).
# BFI82U (三大法人買賣金額) returns a flat table {stat, date, fields, data:[row]}
# in **元**. MI_MARGN?selectType=MS (信用交易統計) returns a multi-table shape
# {stat, date, tables:[{fields, data}, {}]} — the credit-stats table is
# tables[0]; tables[1] comes back empty. Both return a bare {stat: "很抱歉…"}
# (no data/tables key) on a non-trading day. 2026-07-09 is the settled trading
# day; 2026-07-12 (Sunday) is the holiday fixture.
MARKET_DATE_YMD = "20260709"
MARKET_HOLIDAY_YMD = "20260712"

BFI82U_URL = (
    "https://www.twse.com.tw/rwd/zh/fund/BFI82U"
    "?dayDate={date}&type=day&response=json"
)
MARGIN_URL = (
    "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"
    "?date={date}&selectType=MS&response=json"
)


def _ticker_of(row: dict) -> str:
    """Best-effort extraction of the ticker code from a raw row."""
    for key in ("Code", "SecuritiesCompanyCode", "公司代號", "code"):
        if key in row:
            return str(row[key]).strip()
    return ""


def _select(rows: list[dict], want_ticker: str) -> list[dict]:
    """First 5 rows plus the row matching want_ticker (deduped, order-preserving)."""
    selected: list[dict] = list(rows[:5])
    seen = {id(r) for r in selected}
    for row in rows:
        if _ticker_of(row) == want_ticker and id(row) not in seen:
            selected.append(row)
            break
    return selected


def _ssl_context() -> ssl.SSLContext:
    """Verified TLS context that tolerates the TPEx cert's missing SKI extension.

    Some Taiwan gov endpoints (tpex.org.tw) present a chain that violates the
    strict RFC 5280 checks Python 3.12+ enables by default (VERIFY_X509_STRICT),
    raising "Missing Subject Key Identifier". Clearing only that strict flag
    keeps full CA-chain + hostname + expiry verification; it does NOT disable
    verification the way verify=False would.
    """
    ctx = ssl.create_default_context()
    ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return ctx


def _fetch(url: str):
    with httpx.Client(
        timeout=30.0, follow_redirects=True, verify=_ssl_context()
    ) as client:
        resp = client.get(
            url,
            headers={
                "User-Agent": "aism-fixture-recorder/1.0",
                "Accept": "application/json",
            },
        )
        resp.raise_for_status()
        return resp.json()


def _select_positional(rows: list[list], want_ticker: str) -> list[list]:
    """First 5 rows plus the positional row whose code column matches want_ticker."""
    selected: list[list] = list(rows[:5])
    seen = {id(r) for r in selected}
    for row in rows:
        if row and str(row[0]).strip() == want_ticker and id(row) not in seen:
            selected.append(row)
            break
    return selected


def _write(name: str, payload) -> None:
    (FIXTURES_DIR / name).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  wrote -> {name}")


def _record_t86() -> None:
    url = T86_URL.format(date=INSTI_DATE_YMD)
    print(f"GET {url}")
    raw = _fetch(url)
    rows = raw.get("data") or []
    print(f"  stat={raw.get('stat')} rows={len(rows)} fields={len(raw.get('fields', []))}")
    _write(
        "twse_t86.json",
        {
            "stat": raw["stat"],
            "date": raw.get("date"),
            "title": raw.get("title"),
            "fields": raw["fields"],
            "data": _select_positional(rows, "2330"),
        },
    )

    holiday_url = T86_URL.format(date=INSTI_HOLIDAY_YMD)
    print(f"GET {holiday_url}")
    holiday = _fetch(holiday_url)
    print(f"  holiday stat={holiday.get('stat')}")
    _write("twse_t86_holiday.json", holiday)


def _record_tpex_insti() -> None:
    url = TPEX_INSTI_URL.format(date=INSTI_DATE_ROC)
    print(f"GET {url}")
    raw = _fetch(url)
    table = raw["tables"][0]
    rows = table.get("data") or []
    print(f"  stat={raw.get('stat')} rows={len(rows)} fields={len(table.get('fields', []))}")
    _write(
        "tpex_institutional.json",
        {
            "stat": raw.get("stat"),
            "date": raw.get("date"),
            "tables": [
                {
                    "title": table.get("title"),
                    "date": table.get("date"),
                    "fields": table["fields"],
                    "data": _select_positional(rows, "3081"),
                }
            ],
        },
    )

    holiday_url = TPEX_INSTI_URL.format(date=INSTI_HOLIDAY_ROC)
    print(f"GET {holiday_url}")
    holiday = _fetch(holiday_url)
    htable = holiday["tables"][0]
    print(f"  holiday stat={holiday.get('stat')} rows={len(htable.get('data') or [])}")
    _write(
        "tpex_institutional_holiday.json",
        {
            "stat": holiday.get("stat"),
            "date": holiday.get("date"),
            "tables": [
                {
                    "title": htable.get("title"),
                    "date": htable.get("date"),
                    "fields": htable["fields"],
                    "data": htable.get("data") or [],
                }
            ],
        },
    )


def _record_twse_history() -> None:
    y, m = HIST_YM
    url = TWSE_HISTORY_URL.format(date=f"{y}{m}01", ticker=HIST_TWSE_TICKER)
    print(f"GET {url}")
    raw = _fetch(url)
    rows = raw.get("data") or []
    print(f"  stat={raw.get('stat')} rows={len(rows)} fields={raw.get('fields')}")
    _write(
        "twse_history.json",
        {
            "stat": raw["stat"],
            "date": raw.get("date"),
            "title": raw.get("title"),
            "fields": raw["fields"],
            "data": rows,  # ~21 rows, small enough to keep whole
        },
    )

    fy, fm = HIST_FUTURE_YM
    nd_url = TWSE_HISTORY_URL.format(date=f"{fy}{fm}01", ticker=HIST_TWSE_TICKER)
    print(f"GET {nd_url}")
    nodata = _fetch(nd_url)
    print(f"  no-data stat={nodata.get('stat')} keys={sorted(nodata)}")
    _write("twse_history_nodata.json", nodata)


def _record_tpex_history() -> None:
    y, m = HIST_YM
    url = TPEX_HISTORY_URL.format(date=f"{y}/{m}/01", ticker=HIST_TPEX_TICKER)
    print(f"GET {url}")
    raw = _fetch(url)
    table = raw["tables"][0]
    rows = table.get("data") or []
    print(f"  stat={raw.get('stat')} rows={len(rows)} fields={table.get('fields')}")
    _write(
        "tpex_history.json",
        {
            "stat": raw.get("stat"),
            "date": raw.get("date"),
            "code": raw.get("code"),
            "name": raw.get("name"),
            "flagField": raw.get("flagField"),
            "tables": [
                {
                    "title": table.get("title"),
                    "date": table.get("date"),
                    "fields": table["fields"],
                    "data": rows,
                }
            ],
        },
    )

    fy, fm = HIST_FUTURE_YM
    nd_url = TPEX_HISTORY_URL.format(date=f"{fy}/{fm}/01", ticker=HIST_TPEX_TICKER)
    print(f"GET {nd_url}")
    nodata = _fetch(nd_url)
    ntable = nodata["tables"][0]
    print(f"  no-data stat={nodata.get('stat')} rows={len(ntable.get('data') or [])}")
    _write(
        "tpex_history_nodata.json",
        {
            "stat": nodata.get("stat"),
            "date": nodata.get("date"),
            "code": nodata.get("code"),
            "name": nodata.get("name"),
            "flagField": nodata.get("flagField"),
            "tables": [
                {
                    "title": ntable.get("title"),
                    "date": ntable.get("date"),
                    "fields": ntable["fields"],
                    "data": ntable.get("data") or [],
                }
            ],
        },
    )


def _record_bfi82u() -> None:
    url = BFI82U_URL.format(date=MARKET_DATE_YMD)
    print(f"GET {url}")
    raw = _fetch(url)
    rows = raw.get("data") or []
    print(f"  stat={raw.get('stat')} rows={len(rows)} fields={raw.get('fields')}")
    _write(
        "twse_bfi82u.json",
        {
            "stat": raw["stat"],
            "date": raw.get("date"),
            "title": raw.get("title"),
            "fields": raw["fields"],
            "data": rows,  # 6 rows, small enough to keep whole
        },
    )

    holiday_url = BFI82U_URL.format(date=MARKET_HOLIDAY_YMD)
    print(f"GET {holiday_url}")
    holiday = _fetch(holiday_url)
    print(f"  holiday stat={holiday.get('stat')} keys={sorted(holiday)}")
    _write("twse_bfi82u_holiday.json", holiday)


def _record_margin() -> None:
    url = MARGIN_URL.format(date=MARKET_DATE_YMD)
    print(f"GET {url}")
    raw = _fetch(url)
    tables = raw.get("tables") or []
    rows = tables[0].get("data") or [] if tables else []
    print(f"  stat={raw.get('stat')} tables={len(tables)} rows={len(rows)}")
    _write("twse_margin.json", raw)  # keep the real multi-table shape verbatim

    holiday_url = MARGIN_URL.format(date=MARKET_HOLIDAY_YMD)
    print(f"GET {holiday_url}")
    holiday = _fetch(holiday_url)
    print(f"  holiday stat={holiday.get('stat')} keys={sorted(holiday)}")
    _write("twse_margin_holiday.json", holiday)


def _fetch_yahoo(symbol: str):
    """GET one Yahoo chart response via curl_cffi Chrome impersonation.

    Returns the curl_cffi Response (not .json()) so the caller can record the
    error symbol's body even when the status is non-200.
    """
    from curl_cffi import requests as cffi_requests

    url = YAHOO_URL.format(symbol=symbol)
    return cffi_requests.get(url, impersonate="chrome", timeout=30)


def _record_yahoo() -> None:
    """Probe all 7 index symbols; store ^TWII + NVDA + an error-symbol fixture."""
    for i, symbol in enumerate(YAHOO_SYMBOLS):
        if i:
            time.sleep(YAHOO_RATE_LIMIT_SECONDS)
        print(f"GET {YAHOO_URL.format(symbol=symbol)}")
        resp = _fetch_yahoo(symbol)
        resp.raise_for_status()
        raw = resp.json()
        meta = (raw.get("chart", {}).get("result") or [{}])[0].get("meta", {})
        print(
            f"  price={meta.get('regularMarketPrice')} "
            f"prevClose={meta.get('chartPreviousClose')} "
            f"currency={meta.get('currency')} name={meta.get('shortName')}"
        )
        if symbol == "^TWII":
            _write("yahoo_twii.json", raw)
        elif symbol == "NVDA":
            _write("yahoo_nvda.json", raw)

    time.sleep(YAHOO_RATE_LIMIT_SECONDS)
    err_symbol = "INVALID_XYZ"
    print(f"GET {YAHOO_URL.format(symbol=err_symbol)}")
    err_resp = _fetch_yahoo(err_symbol)
    print(f"  status={err_resp.status_code}")
    err_raw = err_resp.json()
    print(f"  chart.error={err_raw.get('chart', {}).get('error')}")
    _write("yahoo_error.json", err_raw)


def _record_mops() -> None:
    for name, url in (("mops_listed", MOPS_LISTED_URL), ("mops_otc", MOPS_OTC_URL)):
        print(f"GET {url}")
        rows = _fetch(url)
        print(f"  same-day count={len(rows)}; keys={list(rows[0]) if rows else '<empty>'}")
        _write(f"{name}.json", rows[:5])


def _record_revenue() -> None:
    for name, url, want in (
        ("revenue_listed", REVENUE_LISTED_URL, REVENUE_LISTED_TICKER),
        ("revenue_otc", REVENUE_OTC_URL, REVENUE_OTC_TICKER),
    ):
        print(f"GET {url}")
        rows = _fetch(url)
        print(
            f"  count={len(rows)}; 資料年月={rows[0].get('資料年月') if rows else '<empty>'}; "
            f"keys={list(rows[0]) if rows else '<empty>'}"
        )
        _write(f"{name}.json", _select(rows, want))


def main() -> None:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

    print(f"GET {TWSE_URL}")
    twse_rows = _fetch(TWSE_URL)
    print(f"  {len(twse_rows)} rows; sample keys: {sorted(twse_rows[0])}")
    twse_sample = _select(twse_rows, "2330")
    (FIXTURES_DIR / "twse_stock_day_all.json").write_text(
        json.dumps(twse_sample, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  wrote {len(twse_sample)} rows -> twse_stock_day_all.json")

    print(f"GET {TPEX_URL}")
    tpex_rows = _fetch(TPEX_URL)
    print(f"  {len(tpex_rows)} rows; sample keys: {sorted(tpex_rows[0])}")
    tpex_sample = _select(tpex_rows, "3081")
    (FIXTURES_DIR / "tpex_daily_close.json").write_text(
        json.dumps(tpex_sample, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  wrote {len(tpex_sample)} rows -> tpex_daily_close.json")

    _record_t86()
    _record_tpex_insti()
    _record_twse_history()
    _record_tpex_history()
    _record_bfi82u()
    _record_margin()
    _record_yahoo()
    _record_mops()


if __name__ == "__main__":
    main()
