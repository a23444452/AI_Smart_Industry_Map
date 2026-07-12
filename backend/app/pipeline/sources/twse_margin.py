"""TWSE 信用交易統計 (MI_MARGN, selectType=MS) source client（市場彙計）.

Endpoint: rwd/zh/marginTrading/MI_MARGN?selectType=MS — the whole-market margin
(融資) / short-sale (融券) buy / sell / balance figures for one trading day.
Date-parameterised (AD ``YYYYMMDD``) so backfill_market_stats can walk it day by
day.

The MS response is a **multi-table** object ``{stat, date, tables:[...]}``: the
信用交易統計 table is ``tables[0]`` (fields ``項目 / 買進 / 賣出 / 現金(券)償還
/ 前日餘額 / 今日餘額``) and ``tables[1]`` comes back as an empty ``{}``, so we
parse ``tables[0]``. Columns are resolved by field name; the 現金(券)償還 column
is intentionally dropped from the neutral output.

``item`` keeps the source's own label verbatim (e.g. ``融資(交易單位)``,
``融券(交易單位)``, ``融資金額(仟元)``) — the unit (張 vs 仟元) lives in that
label, and the raw values are kept as-is (no 張↔股 or 仟元↔元 conversion; that
belongs at the presentation layer).
"""

from __future__ import annotations

import time

from app.pipeline.sources import _common

URL_TEMPLATE = (
    "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"
    "?date={date}&selectType=MS&response=json"
)
_SOURCE = "TWSE-Margin"

# Politeness rate-limit between requests (seconds). Deliberately applied inside
# fetch() rather than by the backfill caller: the only cost is one spurious
# 0.4s sleep before the first request — negligible against a 30-day walk — and
# it keeps every call site throttled by construction instead of by convention.
# 無此限流時 TWSE rwd 端點對連續請求回 HTTP 307，backfill 會逐日被跳過。
_RATE_LIMIT_SECONDS = 0.4

# Real field labels (現金(券)償還 is not carried into the neutral output).
_ITEM = "項目"
_BUY = "買進"
_SELL = "賣出"
_PREV = "前日餘額"
_TODAY = "今日餘額"


def fetch(date: str) -> dict:
    """GET the raw MI_MARGN (MS) response for an ISO ``date`` (e.g. '2026-07-09')."""
    time.sleep(_RATE_LIMIT_SECONDS)  # politeness pacing — see constant above
    url = URL_TEMPLATE.format(date=_common.iso_to_yyyymmdd(date))
    return _common.get_json_dict(url, source=_SOURCE)


def parse(raw: dict, date: str) -> list[dict]:
    """Map raw MI_MARGN (MS) rows to neutral margin-balance dicts.

    Output rows: ``{item, buy, sell, prev_balance, today_balance, date}`` with
    figures as ints (張 or 仟元 per ``item`` label, kept as-is) and ``date`` the
    ISO date passed in. ``date`` 以呼叫端請求日為準，不校驗 response 自帶日期
    （與法人 sources 同契約）。
    Parses the 信用交易統計 table (``tables[0]``; ``tables[1]`` is an empty
    stub). Returns ``[]`` for a holiday / empty response (stat != "OK", no
    table, or empty data); raises SourceFetchError when an expected header
    column disappears (structural drift needs human attention). Missing numeric
    cells stay tolerant (treated as None).
    """
    if raw.get("stat") != "OK":
        return []
    tables = raw.get("tables") or []
    if not tables:
        return []
    table = tables[0]
    data = table.get("data") or []
    if not data:
        return []

    idx = _common.resolve_field_index(
        table.get("fields") or [],
        (_ITEM, _BUY, _SELL, _PREV, _TODAY),
        source=_SOURCE,
    )

    rows: list[dict] = []
    for row in data:
        rows.append(
            {
                "item": str(row[idx[_ITEM]]).strip(),
                "buy": _common.to_int(row[idx[_BUY]]),
                "sell": _common.to_int(row[idx[_SELL]]),
                "prev_balance": _common.to_int(row[idx[_PREV]]),
                "today_balance": _common.to_int(row[idx[_TODAY]]),
                "date": date,
            }
        )
    return rows
