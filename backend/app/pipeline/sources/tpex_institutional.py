"""TPEx (上櫃) 三大法人買賣明細 source client.

Endpoint: www/zh-tw/insti/dailyTrade — every OTC stock's foreign / trust /
dealer net buy-sell (in **shares**) for one trading day. Date-parameterised
(ROC ``115/07/09`` format) so backfill_institutional can walk it day by day.
The TPEx OpenAPI has no per-stock institutional feed, so this uses the web
JSON endpoint.

The response is ``{stat, tables:[{fields, date, data:[row, ...]}]}`` where each
row is a 24-column positional array. Unlike T86 the header labels repeat
(buy / sell / net for every group), so columns are resolved by index. The
groups are, in order: 外資及陸資(不含外資自營商), 外資自營商, 外資及陸資合計,
投信, 自營商(自行), 自營商(避險), 自營商合計, then 三大法人合計.
"""

from __future__ import annotations

from app.pipeline.sources import _common
from app.pipeline.sources._common import SourceFetchError

URL_TEMPLATE = (
    "https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade"
    "?type=Daily&sect=EW&date={date}&response=json"
)
_SOURCE = "TPEx-Insti"

# Positional net columns (0-based) in each data row.
_IDX_TICKER = 0
_IDX_NAME = 1
_IDX_FOREIGN_NET = 10  # 外資及陸資買賣超合計 (already incl. foreign dealer)
_IDX_TRUST_NET = 13  # 投信買賣超
_IDX_DEALER_NET = 22  # 自營商買賣超合計 (自行 + 避險)

_EXPECTED_FIELD_COUNT = 24
_NET_LABEL = "買賣超"  # every net column's header contains this


def _guard_fields(fields: list) -> None:
    """Raise if the header no longer matches the positional mapping above.

    Column drift needs human attention — silently returning [] would make a
    backfill mistake a restructured response for a holiday.
    """
    ok = len(fields) == _EXPECTED_FIELD_COUNT and all(
        _NET_LABEL in str(fields[i])
        for i in (_IDX_FOREIGN_NET, _IDX_TRUST_NET, _IDX_DEALER_NET)
    )
    if not ok:
        raise SourceFetchError(
            _SOURCE, f"{_SOURCE} 資料來源欄位結構變動（TPEx 欄位結構變動），請人工確認"
        )


def fetch(date: str) -> dict:
    """GET the raw institutional response for an ISO ``date`` (e.g. '2026-07-09')."""
    url = URL_TEMPLATE.format(date=_common.iso_to_roc_slash(date))
    return _common.get_json_dict(url, source=_SOURCE)


def parse(raw: dict, date: str) -> list[dict]:
    """Map raw TPEx institutional rows to neutral dicts.

    Output rows: ``{ticker, name, foreign_net, trust_net, dealer_net, date}``
    with net figures as ints (shares) and ``date`` the ISO date passed in.
    ``date`` 以呼叫端請求日為準，不校驗 response 自帶日期。
    Returns ``[]`` for a holiday / empty response (stat != "ok", no table, or
    empty data); raises SourceFetchError if the header no longer matches the
    positional column mapping (drift needs human attention, not silence).
    """
    if str(raw.get("stat", "")).lower() != "ok":
        return []
    tables = raw.get("tables") or []
    if not tables:
        return []
    data = tables[0].get("data") or []
    if not data:
        return []
    _guard_fields(tables[0].get("fields") or [])

    def net(row: list, i: int) -> int:
        return (_common.to_int(row[i]) if i < len(row) else None) or 0

    rows: list[dict] = []
    for row in data:
        rows.append(
            {
                "ticker": str(row[_IDX_TICKER]).strip(),
                "name": str(row[_IDX_NAME]).strip(),
                "foreign_net": net(row, _IDX_FOREIGN_NET),
                "trust_net": net(row, _IDX_TRUST_NET),
                "dealer_net": net(row, _IDX_DEALER_NET),
                "date": date,
            }
        )
    return rows
