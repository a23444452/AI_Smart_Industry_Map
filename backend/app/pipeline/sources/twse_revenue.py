"""月營收 (每月營業收入) source client — 上市 (TWSE).

Endpoint (t187ap05_L, a bare list[dict] of the *latest reported month*, no
date parameter, one row per company):

    上市 TWSE: opendata/t187ap05_L

The 上市 and 上櫃 feeds expose the SAME 中文 columns (unlike the MOPS 重大訊息
feeds, whose keys diverge 中/英), so the 上櫃 client (``tpex_revenue``) reuses
:func:`parse` here rather than re-implementing it. ``parse`` still resolves each
value across candidate keys (with English fallbacks) so a future rename on
either market degrades gracefully instead of crashing.

Revenue unit: the feed reports 營業收入-當月營收 in **千元 (NT$ thousands)** — the
same unit the ``fundamentals`` table stores — so no scaling is applied. (Were a
source ever to switch to 元, the parser would need to divide by 1000.)

Neutral row shape (Task 5 merges 上市 + 上櫃 → filter → upsert on ticker+month):
    ticker  : 公司代號
    month   : 資料年月 (ROC packed "11506" → ISO "2026-06")
    revenue : 營業收入-當月營收 (int 千元, or None when blank/"-")
    yoy     : 營業收入-去年同月增減(%) (float, or None when blank/"-")
"""

from __future__ import annotations

from datetime import date

from app.pipeline.sources import _common
from app.pipeline.sources._common import SourceFetchError

LISTED_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"

SOURCE = "月營收-上市"

# Candidate keys per neutral field (checked in order; first present wins).
# Both markets currently use the 中文 keys; the English fallbacks are defensive.
_TICKER_KEYS = ("公司代號", "SecuritiesCompanyCode", "Code")
_MONTH_KEYS = ("資料年月", "DataYearMonth")
_REVENUE_KEYS = ("營業收入-當月營收", "當月營收", "Revenue")
_YOY_KEYS = ("營業收入-去年同月增減(%)", "去年同月增減(%)", "YoY")

_MISSING = object()


def fetch() -> list[dict]:
    """GET the latest 上市 (TWSE) monthly-revenue snapshot (list of dicts)."""
    return _common.get_json(LISTED_URL, source=SOURCE)


def parse(raw: list[dict]) -> list[dict]:
    """Map raw monthly-revenue rows to neutral dicts.

    Each row → ``{ticker, month, revenue, yoy}``. ``month`` is ISO "YYYY-MM"
    (民國年月 converted); ``revenue`` is an int in 千元; ``yoy`` a float percent.
    Blank / "-" numeric or month fields tolerate to None. A row lacking every
    ticker key is structural drift → raise SourceFetchError. Empty input → [].
    """
    rows: list[dict] = []
    for item in raw:
        ticker = _first(item, _TICKER_KEYS)
        if ticker is _MISSING:
            raise SourceFetchError(
                SOURCE, f"{SOURCE} 資料來源欄位結構變動，請人工確認"
            )
        rows.append(
            {
                "ticker": _text(ticker),
                "month": roc_ym_to_month(_first_or_none(item, _MONTH_KEYS)),
                "revenue": _common.to_int(_first_or_none(item, _REVENUE_KEYS)),
                "yoy": _common.to_number(_first_or_none(item, _YOY_KEYS)),
            }
        )
    return rows


def roc_ym_to_month(raw: object) -> str | None:
    """Convert a ROC year-month to ISO "YYYY-MM"; None for blank/malformed.

    Tolerates both the packed form the feed uses ("11506" → 民國 115 年 06 月 →
    "2026-06") and a slash form ("115/06"). The trailing 2 digits are the month;
    the remaining leading digits are the ROC year (AD = ROC + 1911).
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if "/" in text:
        parts = text.split("/")
        if len(parts) != 2 or not all(p.isdigit() for p in parts):
            return None
        roc_year, month = int(parts[0]), int(parts[1])
    else:
        if not text.isdigit() or len(text) < 4:
            return None
        roc_year, month = int(text[:-2]), int(text[-2:])
    try:
        d = date(roc_year + 1911, month, 1)
    except ValueError:
        return None
    return f"{d.year:04d}-{d.month:02d}"


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


def _text(value: object) -> str:
    """Stringify a possibly-missing value, trimmed; sentinel/None → ''."""
    if value is _MISSING or value is None:
        return ""
    return str(value).strip()
