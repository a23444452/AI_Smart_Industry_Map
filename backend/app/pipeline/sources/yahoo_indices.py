"""Yahoo Finance 指數 source client（每日焦點指數列）.

Endpoint: query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1d
— one nested object ``{chart:{result:[{meta:{...}}], error}}`` per symbol, with
the live quote in ``meta.regularMarketPrice`` and the prior close in
``meta.chartPreviousClose`` (recorded 2026-07-11; see tests/fixtures/yahoo_*).

Transport is ``curl_cffi`` with ``impersonate="chrome"`` instead of the shared
httpx helpers in ``_common``: Yahoo fingerprints the TLS handshake and returns
429 to non-browser clients — httpx/curl are blocked even with a browser
User-Agent header — and Chrome TLS impersonation via curl_cffi is the yfinance
community's standard workaround. curl_cffi is a Yahoo-only dependency; every
other source keeps using ``_common.get_json``/``get_json_dict``.

Error contract matches ``_common``: ``fetch`` raises SourceFetchError on any
connection failure, non-200 (incl. the fingerprint 429 and the 404 an unknown
symbol gets), or unparseable body; ``parse`` raises it when ``chart.error`` is
set or ``chart.result`` is empty — so the job layer (S5-Task 5 fetch_indices)
only ever catches SourceFetchError.
"""

from __future__ import annotations

import time

from curl_cffi import requests as cffi_requests

from app.pipeline.sources._common import SourceFetchError

URL_TEMPLATE = (
    "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    "?interval=1d&range=1d"
)
_SOURCE = "Yahoo"
TIMEOUT_SECONDS = 30

# Politeness rate-limit between requests (seconds). Applied inside fetch() so
# the 7-symbol loop in fetch_indices is throttled by construction, not by
# caller convention (same rationale as twse_history/tpex_history).
_RATE_LIMIT_SECONDS = 0.5

# Tracked symbols -> Chinese display names. Names deliberately come from this
# table, not Yahoo's English shortName/longName, so the 每日焦點 row renders in
# Chinese regardless of what Yahoo returns.
SYMBOLS = {
    "^TWII": "加權指數",
    "^SOX": "費城半導體",
    "^GSPC": "S&P 500",
    "TSM": "台積電 ADR",
    "NVDA": "輝達 NVDA",
    "^N225": "日經 225",
    "^VIX": "VIX 恐慌",
}


def fetch(symbol: str) -> dict:
    """GET the raw chart response for ``symbol`` (rate-limited, Chrome TLS).

    Raises SourceFetchError (friendly message + status code when available) on
    connection/timeout failure, any non-200, or a body that is not a JSON dict.
    """
    time.sleep(_RATE_LIMIT_SECONDS)  # politeness pacing — see constant above
    url = URL_TEMPLATE.format(symbol=symbol)
    try:
        resp = cffi_requests.get(
            url, impersonate="chrome", timeout=TIMEOUT_SECONDS
        )
    except cffi_requests.exceptions.RequestException as exc:
        raise SourceFetchError(
            _SOURCE, f"{_SOURCE} 資料來源連線失敗，請稍後再試"
        ) from exc

    if resp.status_code != 200:
        raise SourceFetchError(
            _SOURCE,
            f"{_SOURCE} 資料來源回應異常（HTTP {resp.status_code}），請稍後再試",
            status_code=resp.status_code,
        )

    try:
        data = resp.json()
    except ValueError as exc:
        raise SourceFetchError(
            _SOURCE,
            f"{_SOURCE} 資料來源回傳內容無法解析，請稍後再試",
            status_code=resp.status_code,
        ) from exc

    if not isinstance(data, dict):
        raise SourceFetchError(
            _SOURCE,
            f"{_SOURCE} 資料來源回傳格式異常，請稍後再試",
            status_code=resp.status_code,
        )
    return data


def parse(raw: dict, symbol: str) -> dict:
    """Map one raw chart response to ``{symbol, name, price, change, change_pct}``.

    ``price`` = ``chart.result[0].meta.regularMarketPrice``; ``change`` /
    ``change_pct`` derive from ``meta.chartPreviousClose`` (both round 2; when
    price or the prior close is missing — or the prior close is 0, division
    guard — both are None). ``name`` comes from the SYMBOLS table.

    Raises SourceFetchError when ``chart.error`` is non-null or ``chart.result``
    is empty — an unknown/delisted symbol needs human attention, not a silent
    empty row.
    """
    chart = raw.get("chart") or {}
    if chart.get("error") is not None or not chart.get("result"):
        raise SourceFetchError(
            _SOURCE, f"{_SOURCE} 資料來源查無 {symbol} 資料，請人工確認"
        )

    meta = chart["result"][0].get("meta") or {}
    price = meta.get("regularMarketPrice")
    prev = meta.get("chartPreviousClose")

    change = change_pct = None
    if price is not None and prev:  # prev None or 0 -> both stay None
        change = round(price - prev, 2)
        change_pct = round((price - prev) / prev * 100, 2)

    return {
        "symbol": symbol,
        "name": SYMBOLS.get(symbol, symbol),
        "price": price,
        "change": change,
        "change_pct": change_pct,
    }
