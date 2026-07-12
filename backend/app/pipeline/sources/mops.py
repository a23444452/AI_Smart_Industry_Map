"""MOPS 重大訊息 (公開資訊觀測站) source client — 上市 + 上櫃.

Endpoints (t187ap04, both bare list[dict], today's filings only, no params):
  上市 TWSE: opendata/t187ap04_L
  上櫃 TPEx: openapi/v1/mopsfin_t187ap04_O

The two feeds label the same columns differently, so ``parse`` resolves each
value across candidate keys rather than a single fixed name:
  ticker : 公司代號 (上市) / SecuritiesCompanyCode (上櫃)
  name   : 公司名稱 (上市) / CompanyName (上櫃)
  title  : "主旨 " (上市, trailing space) / 主旨 (上櫃)
  date   : 發言日期 (ROC packed, e.g. 1150711)
  time   : 發言時間 (packed HHMMSS, leading zero stripped, e.g. "70003")
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.pipeline.sources import _common
from app.pipeline.sources._common import SourceFetchError

LISTED_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap04_L"
OTC_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap04_O"

SOURCE = "MOPS"

_TAIPEI = ZoneInfo("Asia/Taipei")
_UTC = ZoneInfo("UTC")

# Candidate keys per neutral field (checked in order; first present wins).
_TICKER_KEYS = ("公司代號", "SecuritiesCompanyCode")
_NAME_KEYS = ("公司名稱", "CompanyName")
_TITLE_KEYS = ("主旨", "主旨 ")
_DATE_KEYS = ("發言日期",)
_TIME_KEYS = ("發言時間",)

# Ordered classify rule table — specific rules before general ones, so a title
# matching several keywords takes the earliest category (e.g. "澄清…財報" → 澄清回應).
_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("澄清",), "澄清回應"),
    (("自結",), "自結"),
    (("財務報告", "財報"), "財務數據"),
    (("董事會", "股東會", "獨立董事", "治理"), "公司治理"),
)

_MISSING = object()


def fetch_listed() -> list[dict]:
    """GET today's 上市 (TWSE) 重大訊息 (list of per-filing dicts)."""
    return _common.get_json(LISTED_URL, source="MOPS-上市")


def fetch_otc() -> list[dict]:
    """GET today's 上櫃 (TPEx) 重大訊息 (list of per-filing dicts)."""
    return _common.get_json(OTC_URL, source="MOPS-上櫃")


def classify(title: str) -> str:
    """Bucket a 主旨 into a coarse category (see models.MopsAnnouncement).

    Pure, order-sensitive: returns the first rule whose keyword appears in the
    title, else the catch-all 重大事件.
    """
    text = title or ""
    for keywords, category in _RULES:
        if any(keyword in text for keyword in keywords):
            return category
    return "重大事件"


def parse(raw: list[dict]) -> list[dict]:
    """Map raw MOPS rows to neutral dicts.

    Each row → {ticker, name, title, published_at, category}. ``published_at``
    is a naive UTC datetime (Taipei wall-clock − 8h). Rows missing/blank in
    date or time are skipped (not fatal). A row lacking every ticker key is
    structural drift → raise SourceFetchError. Empty input → [].
    """
    rows: list[dict] = []
    for item in raw:
        ticker = _first(item, _TICKER_KEYS)
        if ticker is _MISSING:
            raise SourceFetchError(SOURCE, f"{SOURCE} 資料來源欄位結構變動，請人工確認")

        published_at = _published_at(
            _first(item, _DATE_KEYS), _first(item, _TIME_KEYS)
        )
        if published_at is None:
            continue

        title = _text(_first(item, _TITLE_KEYS))
        rows.append(
            {
                "ticker": _text(ticker),
                "name": _text(_first(item, _NAME_KEYS)),
                "title": title,
                "published_at": published_at,
                "category": classify(title),
            }
        )
    return rows


def _first(row: dict, keys: tuple[str, ...]):
    """Value of the first present key, or the _MISSING sentinel if none present."""
    for key in keys:
        if key in row:
            return row[key]
    return _MISSING


def _text(value: object) -> str:
    """Stringify a possibly-missing value, trimmed; sentinel/None → ''."""
    if value is _MISSING or value is None:
        return ""
    return str(value).strip()


def _published_at(date_raw: object, time_raw: object) -> datetime | None:
    """Combine ROC date + packed HHMMSS (Taipei) into a naive UTC datetime.

    Returns None when either part is missing/blank/malformed, so the caller can
    skip the row without crashing.
    """
    iso = _common.roc_to_iso(None if date_raw is _MISSING else date_raw)
    time_parts = _parse_time(None if time_raw is _MISSING else time_raw)
    if iso is None or time_parts is None:
        return None
    year, month, day = (int(part) for part in iso.split("-"))
    hour, minute, second = time_parts
    aware = datetime(year, month, day, hour, minute, second, tzinfo=_TAIPEI)
    return aware.astimezone(_UTC).replace(tzinfo=None)


def _parse_time(raw: object) -> tuple[int, int, int] | None:
    """Parse 發言時間 into (h, m, s); None for blank/malformed.

    The feed packs the time as HHMMSS with the leading zero stripped
    ("70003" → 07:00:03); colon-separated "19:00:00" is also tolerated.
    """
    if raw is None:
        return None
    text = str(raw).strip().replace(":", "")
    if not text.isdigit():
        return None
    text = text.zfill(6)
    if len(text) != 6:
        return None
    hour, minute, second = int(text[:2]), int(text[2:4]), int(text[4:6])
    if hour > 23 or minute > 59 or second > 59:
        return None
    return hour, minute, second
