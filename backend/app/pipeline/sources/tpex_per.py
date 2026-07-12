"""本益比/殖利率/股價淨值比 source client — 上櫃當日全市場 (TPEx).

Endpoint (tpex_mainboard_peratio_analysis, a bare list[dict] of *today's*
whole-market snapshot, no date parameter, one row per OTC stock):

    上櫃 TPEx: openapi/v1/tpex_mainboard_peratio_analysis

Raw 上櫃 keys: ``Date`` (ROC packed "1150709"), ``SecuritiesCompanyCode``,
``CompanyName``, ``PriceEarningRatio``, ``DividendPerShare``, ``YieldRatio``,
``PriceBookRatio``. This is the same data the 上市 BWIBBU_ALL feed serves under
different key names, so this module only differs by URL + source label and
reuses :func:`twse_per.parse` (candidate keys cover both markets — see that
module's docstring). Task 5 merges 上市 + 上櫃 → upsert on ticker+date.
"""

from __future__ import annotations

from app.pipeline.sources import _common
from app.pipeline.sources.twse_per import parse

__all__ = ["OTC_URL", "SOURCE", "fetch", "parse"]

OTC_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis"

SOURCE = "本益比-上櫃"


def fetch() -> list[dict]:
    """GET the 上櫃 (TPEx) whole-market PER snapshot (list of dicts)."""
    return _common.get_json(OTC_URL, source=SOURCE)
