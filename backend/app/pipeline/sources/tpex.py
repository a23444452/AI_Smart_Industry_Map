"""TPEx (上櫃) daily-close source client.

Endpoint: tpex_mainboard_daily_close_quotes — every OTC main-board stock's
OHLC for the latest trading day. Public open data, no API key.
"""

from __future__ import annotations

from app.pipeline.sources import _common

URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"


def fetch() -> list[dict]:
    """GET the raw TPEx response (list of per-stock dicts)."""
    return _common.get_json(URL, source="TPEx")


def parse(raw: list[dict]) -> list[dict]:
    """Map raw TPEx rows to neutral dicts.

    Real fields → neutral keys:
      SecuritiesCompanyCode→ticker, CompanyName→name, Open→open, High→high,
      Low→low, Close→close, TradingShares→volume,
      Change (signed '+/-' price delta, may have trailing space)→change_pct,
      Date (ROC)→date (ISO).
    """
    rows: list[dict] = []
    for item in raw:
        close = _common.to_number(item.get("Close"))
        change = _common.to_number(item.get("Change"))
        rows.append(
            {
                "ticker": str(item.get("SecuritiesCompanyCode", "")).strip(),
                "name": str(item.get("CompanyName", "")).strip(),
                "open": _common.to_number(item.get("Open")),
                "high": _common.to_number(item.get("High")),
                "low": _common.to_number(item.get("Low")),
                "close": close,
                "volume": _common.to_int(item.get("TradingShares")),
                "change_pct": _common.change_pct(close, change),
                "date": _common.roc_to_iso(item.get("Date")),
            }
        )
    return rows
