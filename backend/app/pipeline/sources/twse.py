"""TWSE (上市) daily-close source client.

Endpoint: exchangeReport/STOCK_DAY_ALL — every listed stock's OHLC for the
latest trading day. Public open data, no API key.
"""

from __future__ import annotations

from app.pipeline.sources import _common

URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"


def fetch() -> list[dict]:
    """GET the raw TWSE response (list of per-stock dicts)."""
    return _common.get_json(URL, source="TWSE")


def parse(raw: list[dict]) -> list[dict]:
    """Map raw TWSE rows to neutral dicts.

    Real fields → neutral keys:
      Code→ticker, Name→name, OpeningPrice→open, HighestPrice→high,
      LowestPrice→low, ClosingPrice→close, TradeVolume→volume,
      Change (signed price delta)→change_pct, Date (ROC)→date (ISO).
    """
    rows: list[dict] = []
    for item in raw:
        close = _common.to_number(item.get("ClosingPrice"))
        change = _common.to_number(item.get("Change"))
        rows.append(
            {
                "ticker": str(item.get("Code", "")).strip(),
                "name": str(item.get("Name", "")).strip(),
                "open": _common.to_number(item.get("OpeningPrice")),
                "high": _common.to_number(item.get("HighestPrice")),
                "low": _common.to_number(item.get("LowestPrice")),
                "close": close,
                "volume": _common.to_int(item.get("TradeVolume")),
                "change_pct": _common.change_pct(close, change),
                "date": _common.roc_to_iso(item.get("Date")),
            }
        )
    return rows
