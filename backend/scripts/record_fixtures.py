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


def _fetch(url: str) -> list[dict]:
    with httpx.Client(
        timeout=30.0, follow_redirects=True, verify=_ssl_context()
    ) as client:
        resp = client.get(url, headers={"User-Agent": "aism-fixture-recorder/1.0"})
        resp.raise_for_status()
        return resp.json()


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


if __name__ == "__main__":
    main()
