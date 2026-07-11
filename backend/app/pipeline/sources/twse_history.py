"""TWSE (上市) 個股月歷史行情 source client (backfill).

Endpoint: rwd/zh/afterTrading/STOCK_DAY — one listed stock's daily OHLCV for a
whole calendar month. Date-parameterised (AD ``YYYYMM01``) so backfill_quotes
can walk month by month to seed the weekly/monthly treemap history.

The response is a table object ``{stat, date, title, fields, data:[row, ...]}``
where each row is a positional array aligned to ``fields``. Columns are
resolved by field name (they are unique and descriptive) so reordering can't
silently corrupt the mapping.
"""

from __future__ import annotations

import time

from app.pipeline.sources import _common

URL_TEMPLATE = (
    "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"
    "?date={date}&stockNo={ticker}&response=json"
)
_SOURCE = "TWSE-History"

# Politeness rate-limit between requests (seconds). Deliberately applied inside
# fetch() rather than by the backfill caller: the only cost is one spurious
# 0.4s sleep before the first request — negligible against a 17-stock ×
# N-month walk — and it keeps every call site throttled by construction
# instead of by convention.
_RATE_LIMIT_SECONDS = 0.4

# Real field labels for the columns we keep. 成交股數 is already in **shares**
# (unlike TPEx's 張/lots), so no unit conversion is needed. 漲跌價差 is dropped:
# the treemap derives period returns from close ratios, not per-day change.
_DATE = "日期"
_OPEN = "開盤價"
_HIGH = "最高價"
_LOW = "最低價"
_CLOSE = "收盤價"
_VOLUME = "成交股數"
_REQUIRED = (_DATE, _OPEN, _HIGH, _LOW, _CLOSE, _VOLUME)


def fetch(ticker: str, year: int, month: int) -> dict:
    """GET the raw STOCK_DAY response for ``ticker`` in ``year``-``month``.

    The date parameter is the AD first-of-month (``YYYYMM01``); the server
    returns every trading day of that month regardless of the day component.
    """
    time.sleep(_RATE_LIMIT_SECONDS)  # politeness pacing — see constant above
    url = URL_TEMPLATE.format(date=f"{year:04d}{month:02d}01", ticker=ticker)
    return _common.get_json_dict(url, source=_SOURCE)


def parse(raw: dict, ticker: str) -> list[dict]:
    """Map raw STOCK_DAY rows to neutral OHLCV dicts.

    Output rows: ``{ticker, date, open, high, low, close, volume, change_pct}``
    with ``date`` ISO, numeric prices as floats (blanks/'--' → None), ``volume``
    an int in shares, and ``change_pct`` always None (history change columns are
    inconsistent; the treemap computes returns from close ratios instead).

    Returns ``[]`` for a future/empty month (stat != "OK" or no data); raises
    SourceFetchError if an expected price/date column disappears (structural
    drift needs human attention, not a silent empty backfill).
    """
    if raw.get("stat") != "OK":
        return []
    data = raw.get("data") or []
    fields = raw.get("fields") or []
    if not data:
        return []

    idx = _common.resolve_field_index(fields, _REQUIRED, source=_SOURCE)

    rows: list[dict] = []
    for row in data:
        rows.append(
            {
                "ticker": ticker,
                "date": _common.roc_slash_to_iso(row[idx[_DATE]]),
                "open": _common.to_number(row[idx[_OPEN]]),
                "high": _common.to_number(row[idx[_HIGH]]),
                "low": _common.to_number(row[idx[_LOW]]),
                "close": _common.to_number(row[idx[_CLOSE]]),
                "volume": _common.to_int(row[idx[_VOLUME]]),
                "change_pct": None,
            }
        )
    return rows
