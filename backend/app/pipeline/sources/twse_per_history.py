"""上市個股月本益比/殖利率/股價淨值比歷史 source client (backfill).

Endpoint (BWIBBU, one listed stock's per-day PER/yield/PBR for a whole calendar
month) — seeds the 河流圖 (streamgraph) valuation history:

    上市 TWSE: rwd/zh/afterTrading/BWIBBU?date={YYYYMM01}&stockNo={ticker}

The response is a table object ``{stat, date, title, fields, data:[row, ...]}``
where each row is a positional array aligned to ``fields``. Columns are resolved
by field name (unique and descriptive) so reordering can't silently corrupt the
mapping. Each row's 日期 is a *Chinese* ROC date ("115年06月01日"), unlike the
slash form the STOCK_DAY history uses.

**上櫃 has no equivalent per-stock month endpoint** — the TPEx afterTrading PER
pages (``peQryDate`` / ``PERatio``) are whole-market *per-date* snapshots (the
``code`` parameter is ignored), not a per-stock time series. Per the slice plan,
上櫃 valuation history is abandoned here and the 上櫃 河流圖 is instead built up
by accumulating the daily ``tpex_per`` snapshots over time.

Neutral row shape (matches the whole-market ``twse_per``/``tpex_per`` output):
    ticker         : passed in (the feed doesn't repeat it per row)
    date           : ISO "YYYY-MM-DD" (中文 ROC 日期 converted)
    per            : 本益比 (float, or None when blank/"-")
    pbr            : 股價淨值比 (float, or None)
    dividend_yield : 殖利率(%) (float, or None)
"""

from __future__ import annotations

import time

from app.pipeline.sources import _common

URL_TEMPLATE = (
    "https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU"
    "?date={date}&stockNo={ticker}&response=json"
)
SOURCE = "本益比歷史-上市"

# Politeness rate-limit between requests (seconds). Applied inside fetch() (not
# by the backfill caller) so every call site is throttled by construction — see
# the identical rationale in ``twse_history``.
_RATE_LIMIT_SECONDS = 0.4

# Real field labels for the columns we keep. 股利年度 / 財報年季 are dropped.
_DATE = "日期"
_YIELD = "殖利率(%)"
_PER = "本益比"
_PBR = "股價淨值比"
_REQUIRED = (_DATE, _YIELD, _PER, _PBR)


def fetch(ticker: str, year: int, month: int) -> dict:
    """GET the raw BWIBBU response for ``ticker`` in ``year``-``month``.

    The date parameter is the AD first-of-month (``YYYYMM01``); the server
    returns every trading day of that month regardless of the day component.
    """
    time.sleep(_RATE_LIMIT_SECONDS)  # politeness pacing — see constant above
    url = URL_TEMPLATE.format(date=f"{year:04d}{month:02d}01", ticker=ticker)
    return _common.get_json_dict(url, source=SOURCE)


def parse(raw: dict, ticker: str) -> list[dict]:
    """Map raw BWIBBU rows to neutral PER dicts.

    Output rows: ``{ticker, date, per, pbr, dividend_yield}`` with ``date`` ISO
    (中文 ROC converted) and numeric ratios as floats (blanks/'--' → None).

    Returns ``[]`` for a future/empty month (stat != "OK" or no data); raises
    SourceFetchError if an expected column disappears (structural drift needs
    human attention, not a silent empty backfill).
    """
    if raw.get("stat") != "OK":
        return []
    data = raw.get("data") or []
    fields = raw.get("fields") or []
    if not data:
        return []

    idx = _common.resolve_field_index(fields, _REQUIRED, source=SOURCE)

    rows: list[dict] = []
    for row in data:
        rows.append(
            {
                "ticker": ticker,
                "date": _common.roc_cn_to_iso(row[idx[_DATE]]),
                "per": _common.to_number(row[idx[_PER]]),
                "pbr": _common.to_number(row[idx[_PBR]]),
                "dividend_yield": _common.to_number(row[idx[_YIELD]]),
            }
        )
    return rows
