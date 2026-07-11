"""Historical backfill jobs — one-shot CLI batch seeding of price/flow history.

Separated from :mod:`app.pipeline.jobs` (which holds the scheduled daily fetch
jobs) because backfill is a different shape of work: it walks per-stock monthly
history and per-day institutional feeds to seed the treemap's trailing window,
and it is resilient — a single stock or single day that fails is logged and
skipped so one bad response can't abort the whole batch.

Both callables obey the runner contract (stage changes only; the runner owns
commit/rollback) and are driven via ``run_job`` from the ``backfill`` CLI
command. Each returns a written-row count for direct-call tests; the CLI
verifies results with sqlite3 rather than the return value.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.pipeline.jobs import _TAIPEI, upsert_institutional_rows
from app.pipeline.sources import tpex_history, tpex_institutional, twse_history, twse_t86

# 每檔最多回溯的月數上限：即使湊不滿目標交易日數也停手，避免無界翻頁。
_MAX_MONTHS = 3


def _prev_month(year: int, month: int) -> tuple[int, int]:
    """(year, month) 的前一個月。"""
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _collect_ticker_history(ticker: str, target_days: int) -> dict[str, dict]:
    """Walk monthly history for one ticker until ``target_days`` or the month cap.

    For each month (newest first): try TWSE STOCK_DAY; if it returns nothing
    (an OTC stock, or a listed one delisted that month), fall back to the TPEx
    tradingStock feed. Rows are deduped by ISO date (first source seen wins).

    Raises whatever the sources raise — the caller wraps each ticker so one
    failure is skipped, not fatal. Collecting the whole ticker before any DB
    write means a mid-walk failure leaves no partial rows for that ticker.
    """
    collected: dict[str, dict] = {}
    year, month = datetime.now(_TAIPEI).date().year, datetime.now(_TAIPEI).date().month
    for _ in range(_MAX_MONTHS):
        rows = twse_history.parse(twse_history.fetch(ticker, year, month), ticker)
        if not rows:
            rows = tpex_history.parse(tpex_history.fetch(ticker, year, month), ticker)
        for row in rows:
            d = row["date"]
            if d and d not in collected:
                collected[d] = row
        if len(collected) >= target_days:
            break
        year, month = _prev_month(year, month)
    return collected


def backfill_quotes(session: Session, days: int = 35) -> int:
    """Seed ``quotes_daily`` with each company's trailing daily OHLCV history.

    Per company: walk months (newest first) via :func:`_collect_ticker_history`
    until it has ``days`` trading days or hits the 3-month cap, then insert only
    ``(ticker, date)`` rows that do **not** already exist — a row already in the
    table (e.g. today's close from ``fetch_tw_quotes``, which carries a real
    ``change_pct``) must never be clobbered by history's ``change_pct=None``.

    A single stock that raises (``SourceFetchError`` or anything else) is logged
    and skipped so one bad response can't abort the batch. Returns the number of
    rows written (for direct-call tests; the CLI verifies via sqlite3).

    Contract: stages changes only; the runner commits/rolls back.
    """
    tickers = list(session.scalars(select(models.Company.ticker)).all())
    written = 0
    skipped = 0
    for ticker in tickers:
        try:
            history = _collect_ticker_history(ticker, days)
        except Exception as exc:  # noqa: BLE001 - one stock must not abort the batch
            skipped += 1
            logger.warning("backfill_quotes: 跳過 {} — {}", ticker, exc)
            continue
        for d, row in history.items():
            if session.get(models.QuoteDaily, (ticker, d)) is not None:
                continue  # 不覆蓋既有列（保留其 change_pct 等既有欄位）
            session.add(
                models.QuoteDaily(
                    ticker=ticker,
                    date=d,
                    open=row["open"],
                    high=row["high"],
                    low=row["low"],
                    close=row["close"],
                    volume=row["volume"],
                    change_pct=row["change_pct"],
                )
            )
            written += 1
    logger.info(
        "backfill_quotes: 寫入 {} 列（{} 檔，跳過 {} 檔）", written, len(tickers), skipped
    )
    return written


def backfill_institutional(session: Session, days: int = 10) -> int:
    """Seed ``institutional_flows`` by walking the last ``days`` calendar days.

    For each calendar day (today back): fetch + parse both T86 and TPEx feeds
    and upsert. Weekends/holidays parse to ``[]`` and are naturally no-ops, so
    walking calendar days (not trading days) needs no holiday calendar. A single
    day that raises is logged and skipped so one bad response can't abort the
    batch. Returns the number of rows written (direct-call tests; CLI uses
    sqlite3).

    Contract: stages changes only; the runner commits/rolls back.
    """
    known = set(session.scalars(select(models.Company.ticker)).all())
    today = datetime.now(_TAIPEI).date()
    written = 0
    for offset in range(days):
        day: date = today - timedelta(days=offset)
        date_iso = day.isoformat()
        try:
            rows = twse_t86.parse(
                twse_t86.fetch(date_iso), date_iso
            ) + tpex_institutional.parse(tpex_institutional.fetch(date_iso), date_iso)
        except Exception as exc:  # noqa: BLE001 - one day must not abort the batch
            logger.warning("backfill_institutional: 跳過 {} — {}", date_iso, exc)
            continue
        written += upsert_institutional_rows(session, rows, known)
    logger.info("backfill_institutional: 寫入 {} 列（近 {} 日）", written, days)
    return written
