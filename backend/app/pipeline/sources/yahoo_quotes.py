"""Yahoo Finance 美股日線 source client（多根 K 棒 OHLCV）.

Endpoint: query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range={range}
— the **same** v8 chart endpoint the index source (:mod:`yahoo_indices`) uses,
but with a multi-day ``range`` ("5d" for the daily fetch, "6mo" for the one-shot
backfill). Instead of a single ``meta.regularMarketPrice`` the response then
carries parallel arrays: ``chart.result[0].timestamp[]`` (epoch seconds, one per
bar) alongside ``indicators.quote[0]`` with ``open/high/low/close/volume`` arrays
(recorded 2026-07-13; see tests/fixtures/yahoo_quotes_*).

Transport is copied verbatim from :mod:`yahoo_indices`: ``curl_cffi`` with
``impersonate="chrome"`` because Yahoo fingerprints the TLS handshake and 429s
non-browser clients. The error contract is identical too — ``fetch`` raises
SourceFetchError on any connection failure, non-200 (incl. the fingerprint 429
and the 404 an unknown/delisted symbol gets), or an unparseable/non-dict body;
``parse`` raises it when ``chart.error`` is set or ``chart.result`` is empty.

The daily fetch job iterates ~287 US tickers, so the politeness pace is a
tighter ``_RATE_LIMIT_SECONDS = 0.3`` (vs the index source's 0.5 over 7 symbols)
applied inside :func:`fetch` — throttling is by construction, not by caller
convention. Yahoo is burst-sensitive; callers must NOT parallelise the loop.
"""

from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo

from curl_cffi import requests as cffi_requests

from app.pipeline.sources._common import SourceFetchError

URL_TEMPLATE = (
    "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    "?interval=1d&range={range}"
)
_SOURCE = "Yahoo"
TIMEOUT_SECONDS = 30

# Politeness rate-limit between requests (seconds). Applied inside fetch() so the
# ~287-symbol loop in fetch_us_quotes is throttled by construction (same
# rationale as yahoo_indices, but tighter given the far larger symbol set).
_RATE_LIMIT_SECONDS = 0.3

# Fallback timezone if meta.exchangeTimezoneName is absent — every US listing
# Yahoo serves reports America/New_York, and the epoch→local-date conversion must
# use the *exchange* day (a US close is already past midnight UTC, so a UTC date
# would tag the bar one day late — see module tests).
_DEFAULT_TZ = "America/New_York"


def fetch(symbol: str, range: str = "5d") -> dict:  # noqa: A002 - Yahoo's param name
    """GET the raw chart response for ``symbol`` over ``range`` (rate-limited, Chrome TLS).

    ``range`` is "5d" for the daily fetch and "6mo" for the historical backfill.
    Raises SourceFetchError (friendly message + status code when available) on
    connection/timeout failure, any non-200 (incl. the 404 an unknown symbol
    returns), or a body that is not a JSON dict.
    """
    time.sleep(_RATE_LIMIT_SECONDS)  # politeness pacing — see constant above
    url = URL_TEMPLATE.format(symbol=symbol, range=range)
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


def _at(seq: list | None, i: int):
    """Element ``i`` of ``seq`` or None (arrays can be shorter than timestamp[])."""
    if seq is None or i >= len(seq):
        return None
    return seq[i]


def parse(raw: dict, symbol: str) -> list[dict]:
    """Map one raw chart response to a list of daily OHLCV rows for ``symbol``.

    Reads ``chart.result[0].timestamp[]`` alongside ``indicators.quote[0]``'s
    open/high/low/close/volume arrays and emits one dict per bar::

        {ticker, date, open, high, low, close, volume, change_pct}

    * ``date`` — the bar's epoch converted to the exchange-local calendar day
      (``meta.exchangeTimezoneName``, America/New_York fallback) as ISO
      ``YYYY-MM-DD``. Using the exchange day, not UTC, keeps a US close on its
      real trading date rather than the next UTC day.
    * bars whose ``close`` is null are skipped entirely (a session with no close
      carries no usable price).
    * ``change_pct`` — percent move vs the previous *emitted* (valid-close) bar,
      round 2; the first emitted bar (and any bar whose prior close is 0) is
      None. Because null-close bars are skipped before this runs, "previous" is
      always the previous valid close in the series.

    Raises SourceFetchError when ``chart.error`` is non-null or ``chart.result``
    is empty — an unknown/delisted symbol needs attention, not a silent [].
    """
    chart = raw.get("chart") or {}
    if chart.get("error") is not None or not chart.get("result"):
        raise SourceFetchError(
            _SOURCE, f"{_SOURCE} 資料來源查無 {symbol} 資料，請人工確認"
        )

    result = chart["result"][0]
    meta = result.get("meta") or {}
    tz = ZoneInfo(meta.get("exchangeTimezoneName") or _DEFAULT_TZ)

    timestamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    opens = quote.get("open")
    highs = quote.get("high")
    lows = quote.get("low")
    closes = quote.get("close")
    volumes = quote.get("volume")

    rows: list[dict] = []
    prev_close: float | None = None
    for i, ts in enumerate(timestamps):
        close = _at(closes, i)
        if close is None:
            continue  # 無收盤的 bar 直接跳過

        change_pct = None
        if prev_close is not None and prev_close != 0:
            change_pct = round((close - prev_close) / prev_close * 100, 2)

        rows.append(
            {
                "ticker": symbol,
                "date": datetime.fromtimestamp(ts, tz).date().isoformat(),
                "open": _at(opens, i),
                "high": _at(highs, i),
                "low": _at(lows, i),
                "close": close,
                "volume": _at(volumes, i),
                "change_pct": change_pct,
            }
        )
        prev_close = close

    return rows
