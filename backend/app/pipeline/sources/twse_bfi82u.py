"""TWSE 三大法人買賣金額統計 (BFI82U) source client（每日焦點市場統計）.

Endpoint: rwd/zh/fund/BFI82U — the whole-market buy / sell / net **金額** (in
**元**, not shares) broken down by 身份別 for one trading day. Date-parameterised
(AD ``YYYYMMDD`` via the ``dayDate`` param) so backfill_market_stats can walk it
day by day.

The response is a flat table ``{stat, date, fields, data:[row, ...]}`` where each
row is a positional array aligned to ``fields`` — same shape as T86. We resolve
columns by field name (they are unique and descriptive) so column reordering
can't silently corrupt the mapping.

``unit`` keeps the source's own 身份別 label verbatim (e.g. ``自營商(自行買賣)``,
``外資及陸資(不含外資自營商)``, ``合計``) — no rewriting, so a caller can trace a
row straight back to the exchange table.
"""

from __future__ import annotations

from app.pipeline.sources import _common

URL_TEMPLATE = (
    "https://www.twse.com.tw/rwd/zh/fund/BFI82U"
    "?dayDate={date}&type=day&response=json"
)
_SOURCE = "TWSE-BFI82U"

# Real field labels (amounts are in 元).
_UNIT = "單位名稱"
_BUY = "買進金額"
_SELL = "賣出金額"
_NET = "買賣差額"


def fetch(date: str) -> dict:
    """GET the raw BFI82U response for an ISO ``date`` (e.g. '2026-07-09')."""
    url = URL_TEMPLATE.format(date=_common.iso_to_yyyymmdd(date))
    return _common.get_json_dict(url, source=_SOURCE)


def parse(raw: dict, date: str) -> list[dict]:
    """Map raw BFI82U rows to neutral market-flow dicts.

    Output rows: ``{unit, buy, sell, net, date}`` with amounts as ints (元) and
    ``date`` the ISO date passed in. ``unit`` is the source's 身份別 label kept
    verbatim (see module docstring). ``date`` 以呼叫端請求日為準，不校驗
    response 自帶日期（與法人 sources 同契約）。
    Returns ``[]`` for a holiday / empty response (stat != "OK" or no data);
    raises SourceFetchError when an expected header column disappears
    (structural drift needs human attention). Missing numeric cells stay
    tolerant (treated as None).
    """
    if raw.get("stat") != "OK":
        return []
    data = raw.get("data") or []
    fields = raw.get("fields") or []
    if not data:
        return []

    idx = _common.resolve_field_index(
        fields, (_UNIT, _BUY, _SELL, _NET), source=_SOURCE
    )

    rows: list[dict] = []
    for row in data:
        rows.append(
            {
                "unit": str(row[idx[_UNIT]]).strip(),
                "buy": _common.to_int(row[idx[_BUY]]),
                "sell": _common.to_int(row[idx[_SELL]]),
                "net": _common.to_int(row[idx[_NET]]),
                "date": date,
            }
        )
    return rows
