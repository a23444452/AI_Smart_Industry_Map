"""TPEx (上櫃) 個股月歷史行情 source client (backfill).

Endpoint: www/zh-tw/afterTrading/tradingStock — one OTC stock's daily OHLCV for
a whole calendar month. Date-parameterised with an **AD** ``YYYY/MM/DD`` string
(the day component is ignored; the server returns the whole month). The TPEx
OpenAPI has no per-stock history feed, so this uses the web JSON endpoint.

The response is ``{stat, tables:[{fields, date, data:[row, ...]}], ...}`` where
each row is a positional array aligned to ``fields``. Columns are resolved by
field name (whitespace-normalised, since headers like '日 期' carry an internal
space) so reordering can't silently corrupt the mapping.
"""

from __future__ import annotations

import time

from app.pipeline.sources import _common

URL_TEMPLATE = (
    "https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock"
    "?code={ticker}&date={date}&response=json"
)
_SOURCE = "TPEx-History"

# Politeness rate-limit between requests (seconds). Deliberately applied inside
# fetch() rather than by the backfill caller: the only cost is one spurious
# 0.4s sleep before the first request — negligible against a 17-stock ×
# N-month walk — and it keeps every call site throttled by construction
# instead of by convention.
_RATE_LIMIT_SECONDS = 0.4

# TPEx reports 成交張數 in **張 (lots)** — the response's own flagField is '張數'
# — whereas TWSE STOCK_DAY and both daily-close sources use shares. Multiply by
# this to normalise volume to shares so the whole pipeline speaks one unit.
_SHARES_PER_LOT = 1000

# Field labels after whitespace normalisation (see _norm). 漲跌 is dropped:
# the treemap derives period returns from close ratios, not per-day change.
_DATE = "日期"
_OPEN = "開盤"
_HIGH = "最高"
_LOW = "最低"
_CLOSE = "收盤"
_VOLUME = "成交張數"
_REQUIRED = (_DATE, _OPEN, _HIGH, _LOW, _CLOSE, _VOLUME)


def _norm(name: object) -> str:
    """Drop all whitespace from a header label ('日 期' -> '日期')."""
    return "".join(str(name).split())


def fetch(ticker: str, year: int, month: int) -> dict:
    """GET the raw tradingStock response for ``ticker`` in ``year``-``month``.

    The date parameter is an AD ``YYYY/MM/DD`` string fixed to the first of the
    month; the server returns every trading day of that month.
    """
    time.sleep(_RATE_LIMIT_SECONDS)  # politeness pacing — see constant above
    url = URL_TEMPLATE.format(ticker=ticker, date=f"{year:04d}/{month:02d}/01")
    return _common.get_json_dict(url, source=_SOURCE)


def parse(raw: dict, ticker: str) -> list[dict]:
    """Map raw tradingStock rows to neutral OHLCV dicts.

    Output rows: ``{ticker, date, open, high, low, close, volume, change_pct}``
    with ``date`` ISO, numeric prices as floats (blanks/'--' → None), ``volume``
    an int in **shares** (張 → shares, ×1000), and ``change_pct`` always None
    (history change columns are inconsistent; the treemap computes returns from
    close ratios instead).

    Returns ``[]`` for a future/empty month (stat != "ok", no table, or empty
    data); raises SourceFetchError if an expected price/date column disappears
    (structural drift needs human attention, not a silent empty backfill).
    """
    if str(raw.get("stat", "")).lower() != "ok":
        return []
    tables = raw.get("tables") or []
    if not tables:
        return []
    table = tables[0]
    data = table.get("data") or []
    if not data:
        return []

    idx = _common.resolve_field_index(
        table.get("fields") or [], _REQUIRED, source=_SOURCE, normalize=_norm
    )

    rows: list[dict] = []
    for row in data:
        lots = _common.to_int(row[idx[_VOLUME]])
        rows.append(
            {
                "ticker": ticker,
                "date": _common.roc_slash_to_iso(row[idx[_DATE]]),
                "open": _common.to_number(row[idx[_OPEN]]),
                "high": _common.to_number(row[idx[_HIGH]]),
                "low": _common.to_number(row[idx[_LOW]]),
                "close": _common.to_number(row[idx[_CLOSE]]),
                "volume": lots * _SHARES_PER_LOT if lots is not None else None,
                "change_pct": None,
            }
        )
    return rows
