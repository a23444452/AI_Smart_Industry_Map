"""本益比/殖利率/股價淨值比 source client — 上市當日全市場 (TWSE).

Endpoint (BWIBBU_ALL, a bare list[dict] of *today's* whole-market snapshot, no
date parameter, one row per listed stock):

    上市 TWSE: exchangeReport/BWIBBU_ALL

Raw 上市 keys: ``Date`` (ROC packed "1150709"), ``Code``, ``Name``, ``PEratio``,
``DividendYield``, ``PBratio``. The 上櫃 (TPEx) feed exposes the SAME data under
English aliases (``SecuritiesCompanyCode`` / ``PriceEarningRatio`` /
``YieldRatio`` / ``PriceBookRatio``), so the 上櫃 client (``tpex_per``) reuses
:func:`parse` here — ``parse`` resolves each value across candidate keys so a
future rename on either market degrades gracefully instead of crashing.

Date handling: both feeds currently carry a per-row ``Date`` column, but the
whole-market snapshots are "today's" data with no session date the caller can
count on being present, so :func:`parse` also takes the Taipei trading ``date``
the job resolves. The row's own ``Date`` wins when parseable; the caller date is
the fallback (a row missing/blank Date, or a future feed dropping the column).

Neutral row shape (Task 5 fetch_per merges 上市 + 上櫃 → upsert on ticker+date):
    ticker         : Code / SecuritiesCompanyCode
    date           : ISO "YYYY-MM-DD" (row Date, else caller date)
    per            : 本益比 (float, or None when blank/"-")
    pbr            : 股價淨值比 (float, or None)
    dividend_yield : 殖利率 % (float, or None)
"""

from __future__ import annotations

from app.pipeline.sources import _common
from app.pipeline.sources._common import SourceFetchError

LISTED_URL = "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL"

SOURCE = "本益比-上市"

# Candidate keys per neutral field (checked in order; first present wins). The
# 中文 fallbacks are defensive against a future rename to the label form.
_TICKER_KEYS = ("Code", "SecuritiesCompanyCode", "公司代號")
_DATE_KEYS = ("Date", "日期")
_PER_KEYS = ("PEratio", "PriceEarningRatio", "本益比")
_PBR_KEYS = ("PBratio", "PriceBookRatio", "股價淨值比")
_YIELD_KEYS = ("DividendYield", "YieldRatio", "殖利率(%)", "殖利率")

_MISSING = object()


def fetch() -> list[dict]:
    """GET the 上市 (TWSE) whole-market PER snapshot (list of dicts)."""
    return _common.get_json(LISTED_URL, source=SOURCE)


def parse(raw: list[dict], date: str) -> list[dict]:
    """Map raw BWIBBU_ALL / peratio_analysis rows to neutral PER dicts.

    Each row → ``{ticker, date, per, pbr, dividend_yield}``. ``date`` is ISO —
    the row's own ROC-packed Date when parseable, else the caller-supplied
    trading ``date``. Ratios tolerate blank / "-" / "N/A" to None. A row lacking
    every ticker key is structural drift → raise SourceFetchError. Empty
    input → [].
    """
    rows: list[dict] = []
    for item in raw:
        ticker = _first(item, _TICKER_KEYS)
        if ticker is _MISSING:
            raise SourceFetchError(SOURCE, f"{SOURCE} 資料來源欄位結構變動，請人工確認")
        row_date = _common.roc_to_iso(_first_or_none(item, _DATE_KEYS))
        rows.append(
            {
                "ticker": str(ticker).strip(),
                "date": row_date or date,
                "per": _common.to_number(_first_or_none(item, _PER_KEYS)),
                "pbr": _common.to_number(_first_or_none(item, _PBR_KEYS)),
                "dividend_yield": _common.to_number(_first_or_none(item, _YIELD_KEYS)),
            }
        )
    return rows


def _first(row: dict, keys: tuple[str, ...]):
    """Value of the first present key, or the _MISSING sentinel if none present."""
    for key in keys:
        if key in row:
            return row[key]
    return _MISSING


def _first_or_none(row: dict, keys: tuple[str, ...]):
    """Like _first but returns None (not the sentinel) when no key is present."""
    value = _first(row, keys)
    return None if value is _MISSING else value
