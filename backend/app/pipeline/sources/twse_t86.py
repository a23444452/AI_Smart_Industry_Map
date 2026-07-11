"""TWSE (上市) 三大法人買賣超 (T86) source client.

Endpoint: rwd/zh/fund/T86 — every listed stock's foreign / investment-trust /
dealer net buy-sell (in **shares**) for one trading day. Unlike the OpenAPI
snapshot endpoints this one is date-parameterised, so backfill_institutional
can walk it day by day.

The response is a table object ``{stat, date, fields, data:[row, ...]}`` where
each row is a positional array aligned to ``fields``. We resolve columns by
field name (they are unique and descriptive) so column reordering can't
silently corrupt the mapping.
"""

from __future__ import annotations

from app.pipeline.sources import _common
from app.pipeline.sources._common import SourceFetchError

URL_TEMPLATE = (
    "https://www.twse.com.tw/rwd/zh/fund/T86"
    "?date={date}&selectType=ALLBUT0999&response=json"
)
_SOURCE = "TWSE-T86"

# Real field labels → their role. Foreign total = 外陸資 (excl. foreign dealer)
# + 外資自營商; dealer total is the source's own combined column, which equals
# 自行 + 避險.
_TICKER = "證券代號"
_NAME = "證券名稱"
_FOREIGN_EXCL_DEALER = "外陸資買賣超股數(不含外資自營商)"
_FOREIGN_DEALER = "外資自營商買賣超股數"
_TRUST = "投信買賣超股數"
_DEALER = "自營商買賣超股數"


def fetch(date: str) -> dict:
    """GET the raw T86 response for an ISO ``date`` (e.g. '2026-07-09')."""
    url = URL_TEMPLATE.format(date=_common.iso_to_yyyymmdd(date))
    return _common.get_json_dict(url, source=_SOURCE)


def parse(raw: dict, date: str) -> list[dict]:
    """Map raw T86 rows to neutral institutional-flow dicts.

    Output rows: ``{ticker, name, foreign_net, trust_net, dealer_net, date}``
    with net figures as ints (shares) and ``date`` the ISO date passed in.
    ``date`` 以呼叫端請求日為準，不校驗 response 自帶日期。
    Returns ``[]`` for a holiday / empty response (stat != "OK" or no data);
    raises SourceFetchError when the ticker/name header columns disappear
    (structural drift needs human attention). Missing numeric columns stay
    tolerant (treated as 0).
    """
    if raw.get("stat") != "OK":
        return []
    data = raw.get("data") or []
    fields = raw.get("fields") or []
    if not data:
        return []

    # Header labels are matched after strip() so incidental whitespace in the
    # source header can't break the mapping.
    idx = {str(name).strip(): i for i, name in enumerate(fields)}
    if _TICKER not in idx or _NAME not in idx:
        raise SourceFetchError(
            _SOURCE, f"{_SOURCE} 資料來源欄位結構變動（T86 欄位結構變動），請人工確認"
        )

    def net(row: list, field: str) -> int:
        value = _common.to_int(row[idx[field]]) if field in idx else None
        return value or 0

    rows: list[dict] = []
    for row in data:
        rows.append(
            {
                "ticker": str(row[idx[_TICKER]]).strip(),
                "name": str(row[idx[_NAME]]).strip(),
                "foreign_net": net(row, _FOREIGN_EXCL_DEALER)
                + net(row, _FOREIGN_DEALER),
                "trust_net": net(row, _TRUST),
                "dealer_net": net(row, _DEALER),
                "date": date,
            }
        )
    return rows
