"""Record real TWSE/TPEx OpenAPI responses into test fixtures.

Fetches the two public endpoints and stores a small representative slice
(first 5 rows + the row containing a known ticker) into the fixtures dir,
preserving the raw field names exactly as returned by the source.

Run once, manually, to (re)generate fixtures:

    uv run python scripts/record_fixtures.py
"""

from __future__ import annotations

import json
import ssl
from pathlib import Path

import httpx

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

TWSE_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TPEX_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"

# Institutional (三大法人) — date-parameterised, table-shaped responses.
# T86 returns a dict {stat, date, fields, data:[row,...]}; TPEx dailyTrade
# returns {stat, tables:[{fields, date, data:[row,...]}]}. Both list rows as
# positional arrays, so a fixture keeps the `fields` header alongside `data`.
# 2026-07-09 (ROC 115/07/09) is the latest trading day the live servers hold;
# 2026-07-10/11 return an empty "no data" response (recorded as the holiday
# fixtures) — the task's suggested 2026-07-10 is not a settled trading day.
INSTI_DATE_ISO = "2026-07-09"
INSTI_DATE_YMD = "20260709"
INSTI_DATE_ROC = "115/07/09"
INSTI_HOLIDAY_YMD = "20260711"
INSTI_HOLIDAY_ROC = "115/07/11"

T86_URL = (
    "https://www.twse.com.tw/rwd/zh/fund/T86"
    "?date={date}&selectType=ALLBUT0999&response=json"
)
TPEX_INSTI_URL = (
    "https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade"
    "?type=Daily&sect=EW&date={date}&response=json"
)


def _ticker_of(row: dict) -> str:
    """Best-effort extraction of the ticker code from a raw row."""
    for key in ("Code", "SecuritiesCompanyCode", "code"):
        if key in row:
            return str(row[key]).strip()
    return ""


def _select(rows: list[dict], want_ticker: str) -> list[dict]:
    """First 5 rows plus the row matching want_ticker (deduped, order-preserving)."""
    selected: list[dict] = list(rows[:5])
    seen = {id(r) for r in selected}
    for row in rows:
        if _ticker_of(row) == want_ticker and id(row) not in seen:
            selected.append(row)
            break
    return selected


def _ssl_context() -> ssl.SSLContext:
    """Verified TLS context that tolerates the TPEx cert's missing SKI extension.

    Some Taiwan gov endpoints (tpex.org.tw) present a chain that violates the
    strict RFC 5280 checks Python 3.12+ enables by default (VERIFY_X509_STRICT),
    raising "Missing Subject Key Identifier". Clearing only that strict flag
    keeps full CA-chain + hostname + expiry verification; it does NOT disable
    verification the way verify=False would.
    """
    ctx = ssl.create_default_context()
    ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return ctx


def _fetch(url: str):
    with httpx.Client(
        timeout=30.0, follow_redirects=True, verify=_ssl_context()
    ) as client:
        resp = client.get(
            url,
            headers={
                "User-Agent": "aism-fixture-recorder/1.0",
                "Accept": "application/json",
            },
        )
        resp.raise_for_status()
        return resp.json()


def _select_positional(rows: list[list], want_ticker: str) -> list[list]:
    """First 5 rows plus the positional row whose code column matches want_ticker."""
    selected: list[list] = list(rows[:5])
    seen = {id(r) for r in selected}
    for row in rows:
        if row and str(row[0]).strip() == want_ticker and id(row) not in seen:
            selected.append(row)
            break
    return selected


def _write(name: str, payload) -> None:
    (FIXTURES_DIR / name).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  wrote -> {name}")


def _record_t86() -> None:
    url = T86_URL.format(date=INSTI_DATE_YMD)
    print(f"GET {url}")
    raw = _fetch(url)
    rows = raw.get("data") or []
    print(f"  stat={raw.get('stat')} rows={len(rows)} fields={len(raw.get('fields', []))}")
    _write(
        "twse_t86.json",
        {
            "stat": raw["stat"],
            "date": raw.get("date"),
            "title": raw.get("title"),
            "fields": raw["fields"],
            "data": _select_positional(rows, "2330"),
        },
    )

    holiday_url = T86_URL.format(date=INSTI_HOLIDAY_YMD)
    print(f"GET {holiday_url}")
    holiday = _fetch(holiday_url)
    print(f"  holiday stat={holiday.get('stat')}")
    _write("twse_t86_holiday.json", holiday)


def _record_tpex_insti() -> None:
    url = TPEX_INSTI_URL.format(date=INSTI_DATE_ROC)
    print(f"GET {url}")
    raw = _fetch(url)
    table = raw["tables"][0]
    rows = table.get("data") or []
    print(f"  stat={raw.get('stat')} rows={len(rows)} fields={len(table.get('fields', []))}")
    _write(
        "tpex_institutional.json",
        {
            "stat": raw.get("stat"),
            "date": raw.get("date"),
            "tables": [
                {
                    "title": table.get("title"),
                    "date": table.get("date"),
                    "fields": table["fields"],
                    "data": _select_positional(rows, "3081"),
                }
            ],
        },
    )

    holiday_url = TPEX_INSTI_URL.format(date=INSTI_HOLIDAY_ROC)
    print(f"GET {holiday_url}")
    holiday = _fetch(holiday_url)
    htable = holiday["tables"][0]
    print(f"  holiday stat={holiday.get('stat')} rows={len(htable.get('data') or [])}")
    _write(
        "tpex_institutional_holiday.json",
        {
            "stat": holiday.get("stat"),
            "date": holiday.get("date"),
            "tables": [
                {
                    "title": htable.get("title"),
                    "date": htable.get("date"),
                    "fields": htable["fields"],
                    "data": htable.get("data") or [],
                }
            ],
        },
    )


def main() -> None:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

    print(f"GET {TWSE_URL}")
    twse_rows = _fetch(TWSE_URL)
    print(f"  {len(twse_rows)} rows; sample keys: {sorted(twse_rows[0])}")
    twse_sample = _select(twse_rows, "2330")
    (FIXTURES_DIR / "twse_stock_day_all.json").write_text(
        json.dumps(twse_sample, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  wrote {len(twse_sample)} rows -> twse_stock_day_all.json")

    print(f"GET {TPEX_URL}")
    tpex_rows = _fetch(TPEX_URL)
    print(f"  {len(tpex_rows)} rows; sample keys: {sorted(tpex_rows[0])}")
    tpex_sample = _select(tpex_rows, "3081")
    (FIXTURES_DIR / "tpex_daily_close.json").write_text(
        json.dumps(tpex_sample, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  wrote {len(tpex_sample)} rows -> tpex_daily_close.json")

    _record_t86()
    _record_tpex_insti()


if __name__ == "__main__":
    main()
