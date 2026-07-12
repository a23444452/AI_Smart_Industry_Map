"""月營收 (每月營業收入) source client — 上櫃 (TPEx).

Endpoint (mopsfin_t187ap05_O, a bare list[dict] of the *latest reported month*,
no date parameter, one row per company):

    上櫃 TPEx: openapi/v1/mopsfin_t187ap05_O

The 上櫃 feed uses the identical 中文 schema as the 上市 feed, so this module
only differs by URL + source label and reuses :func:`twse_revenue.parse`
(candidate keys, ROC year-month conversion, 千元 revenue unit — see that module's
docstring). Task 5 merges 上市 + 上櫃 → filter → upsert on ticker+month.
"""

from __future__ import annotations

from app.pipeline.sources import _common
from app.pipeline.sources.twse_revenue import parse, roc_ym_to_month

__all__ = ["OTC_URL", "SOURCE", "fetch", "parse", "roc_ym_to_month"]

OTC_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O"

SOURCE = "月營收-上櫃"


def fetch() -> list[dict]:
    """GET the latest 上櫃 (TPEx) monthly-revenue snapshot (list of dicts)."""
    return _common.get_json(OTC_URL, source=SOURCE)
