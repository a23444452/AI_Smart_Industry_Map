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
from app.pipeline.jobs import _TAIPEI, _known_tickers, upsert_institutional_rows
from app.pipeline.jobs_daily import _upsert_margin_balances, _upsert_market_flows
from app.pipeline.sources import (
    tpex_history,
    tpex_institutional,
    twse_bfi82u,
    twse_history,
    twse_margin,
    twse_per_history,
    twse_t86,
)

# 每檔最多回溯的月數上限：即使湊不滿目標交易日數也停手，避免無界翻頁。
_MAX_MONTHS = 6


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
    today = datetime.now(_TAIPEI).date()  # 取一次，避免跨午夜時 year/month 不一致
    year, month = today.year, today.month
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
    if tickers and skipped == len(tickers):
        # 全部檔都失敗不是個別股票的問題——多半是端點掛掉/封鎖或欄位全面變動，
        # 屬系統性失敗，升級為 error 讓人工注意（單檔失敗仍只是 warning）。
        logger.error(
            "backfill_quotes: 全部 {} 檔皆失敗，疑似系統性失敗（端點異常或結構變動），請人工確認",
            len(tickers),
        )
    logger.info(
        "backfill_quotes: 寫入 {} 列（{} 檔，跳過 {} 檔）", written, len(tickers), skipped
    )
    return written


def backfill_institutional(session: Session, days: int = 14) -> int:
    """Seed ``institutional_flows`` by walking the last ``days`` calendar days.

    ``days=14`` 預設：日曆日中夾雜週末與國定假日（春節等長假可連休 4+ 日），
    14 個日曆日約保證 8–10 個交易日的法人資料；10 日在長假期邊界可能只剩 5–6
    個交易日，不足以畫趨勢。

    For each calendar day (today back): fetch + parse both T86 and TPEx feeds
    and upsert. Weekends/holidays parse to ``[]`` and are naturally no-ops, so
    walking calendar days (not trading days) needs no holiday calendar. A single
    day that raises is logged and skipped so one bad response can't abort the
    batch; if **every** day raises, that is escalated to ``logger.error`` as a
    suspected systemic failure（假日的空回應不 raise，不算失敗）. Returns the
    number of rows written (direct-call tests; CLI uses sqlite3).

    Contract: stages changes only; the runner commits/rolls back.
    """
    known = _known_tickers(session)
    today = datetime.now(_TAIPEI).date()
    written = 0
    failed_days = 0
    for offset in range(days):
        day: date = today - timedelta(days=offset)
        date_iso = day.isoformat()
        try:
            rows = twse_t86.parse(
                twse_t86.fetch(date_iso), date_iso
            ) + tpex_institutional.parse(tpex_institutional.fetch(date_iso), date_iso)
        except Exception as exc:  # noqa: BLE001 - one day must not abort the batch
            failed_days += 1
            logger.warning("backfill_institutional: 跳過 {} — {}", date_iso, exc)
            continue
        written += upsert_institutional_rows(session, rows, known)
    if days and failed_days == days:
        # 每一天都 exception（非假日空回應）→ 疑似端點掛掉或結構全面變動，
        # 屬系統性失敗，升級為 error 讓人工注意。
        logger.error(
            "backfill_institutional: 近 {} 日全部失敗，疑似系統性失敗（端點異常或結構變動），請人工確認",
            days,
        )
    logger.info("backfill_institutional: 寫入 {} 列（近 {} 日）", written, days)
    return written


def backfill_market_stats(session: Session, days: int = 30) -> int:
    """Seed ``market_flows`` + ``margin_balances`` over the last ``days`` days.

    Mirrors :func:`backfill_institutional`: for each calendar day (today back)
    fetch + parse both BFI82U and MI_MARGN and upsert via the shared
    ``jobs_daily`` helpers. Weekends/holidays parse to ``[]`` (natural no-ops),
    so walking calendar days needs no holiday calendar. A single day that raises
    is logged and skipped so one bad response can't abort the batch; if **every**
    day raises, that is escalated to ``logger.error`` as a suspected systemic
    failure（假日的空回應不 raise，不算失敗）. Returns the number of rows written
    (direct-call tests; CLI uses sqlite3).

    Contract: stages changes only; the runner commits/rolls back.
    """
    today = datetime.now(_TAIPEI).date()
    written = 0
    failed_days = 0
    for offset in range(days):
        day: date = today - timedelta(days=offset)
        date_iso = day.isoformat()
        try:
            # 兩來源共用一個 try：單日原子（任一來源失敗即整天跳過、不留半天資料），
            # 與 daily job fetch_market_stats 的「兩來源各自隔離」刻意不同——backfill
            # 走 30 日，缺一天可重跑補齊；daily 只有當天一次機會，能撈多少是多少。
            flows = twse_bfi82u.parse(twse_bfi82u.fetch(date_iso), date_iso)
            margins = twse_margin.parse(twse_margin.fetch(date_iso), date_iso)
        except Exception as exc:  # noqa: BLE001 - one day must not abort the batch
            failed_days += 1
            logger.warning("backfill_market_stats: 跳過 {} — {}", date_iso, exc)
            continue
        written += _upsert_market_flows(session, flows)
        written += _upsert_margin_balances(session, margins)
    if days and failed_days == days:
        # 每一天都 exception（非假日空回應）→ 疑似端點掛掉或結構全面變動，
        # 屬系統性失敗，升級為 error 讓人工注意。
        logger.error(
            "backfill_market_stats: 近 {} 日全部失敗，疑似系統性失敗（端點異常或結構變動），請人工確認",
            days,
        )
    logger.info("backfill_market_stats: 寫入 {} 列（近 {} 日）", written, days)
    return written


# --------------------------------------------------------------------------- #
# backfill_per — 每檔月本益比歷史 into per_daily
# --------------------------------------------------------------------------- #


def _collect_ticker_per_history(ticker: str, months: int) -> dict[str, dict]:
    """Walk ``months`` calendar months (newest first) of one ticker's PER history.

    A deliberate *parallel* of :func:`_collect_ticker_history` (quotes) rather
    than a reuse of it, because two of that walk's traits don't fit PER backfill:

    * **No TPEx fallback** — 上櫃 has no per-stock month endpoint (see
      ``twse_per_history`` docstring), so an OTC ticker simply collects nothing
      here (the 上市 endpoint returns no rows for an OTC 代號) and is a natural
      no-op; there is no second source to try.
    * **No target-day early-stop** — PER backfill wants every trading day across
      the fixed ``months`` window, so it always walks the full range.

    Rows are deduped by ISO date. Raises whatever the source raises — the caller
    wraps each ticker so one failure is skipped, not fatal; collecting the whole
    ticker before any DB write means a mid-walk failure leaves no partial rows.
    """
    collected: dict[str, dict] = {}
    today = datetime.now(_TAIPEI).date()  # 取一次，避免跨午夜時 year/month 不一致
    year, month = today.year, today.month
    for _ in range(months):
        rows = twse_per_history.parse(
            twse_per_history.fetch(ticker, year, month), ticker
        )
        for row in rows:
            d = row["date"]
            if d and d not in collected:
                collected[d] = row
        year, month = _prev_month(year, month)
    return collected


def backfill_per(session: Session, months: int = 3) -> int:
    """Seed ``per_daily`` with each company's trailing monthly PER/PBR/yield history.

    Per company: walk ``months`` months (newest first) via
    :func:`_collect_ticker_per_history`, then insert only ``(ticker, date)`` rows
    that do **not** already exist — insert-only mirrors :func:`backfill_quotes`
    so a row today's :func:`~app.pipeline.jobs_daily.fetch_per` already wrote is
    never re-touched. 上櫃 檔自然回空（上市月檔端點對上櫃代號無資料）→ no-op.

    A single stock that raises (``SourceFetchError`` or anything else) is logged
    and skipped so one bad response can't abort the batch; if **every** stock
    fails that is escalated to ``logger.error`` as a suspected systemic failure.
    Returns the number of rows written (direct-call tests; CLI verifies via
    sqlite3).

    Contract: stages changes only; the runner commits/rolls back.
    """
    tickers = list(session.scalars(select(models.Company.ticker)).all())
    written = 0
    skipped = 0
    for ticker in tickers:
        try:
            history = _collect_ticker_per_history(ticker, months)
        except Exception as exc:  # noqa: BLE001 - one stock must not abort the batch
            skipped += 1
            logger.warning("backfill_per: 跳過 {} — {}", ticker, exc)
            continue
        for d, row in history.items():
            if session.get(models.PerDaily, (ticker, d)) is not None:
                continue  # 不覆蓋既有列（保留 fetch_per 當日已寫入的值）
            session.add(
                models.PerDaily(
                    ticker=ticker,
                    date=d,
                    per=row["per"],
                    pbr=row["pbr"],
                    dividend_yield=row["dividend_yield"],
                )
            )
            written += 1
    if tickers and skipped == len(tickers):
        # 全部檔皆失敗多半是端點掛掉/封鎖或欄位全面變動，屬系統性失敗，升級為 error
        # 讓人工注意（單檔失敗仍只是 warning）。
        logger.error(
            "backfill_per: 全部 {} 檔皆失敗，疑似系統性失敗（端點異常或結構變動），請人工確認",
            len(tickers),
        )
    logger.info(
        "backfill_per: 寫入 {} 列（{} 檔，跳過 {} 檔）", written, len(tickers), skipped
    )
    return written
