"""Pipeline jobs — callables ``fn(session)`` driven by the runner.

A job stages DB changes on the session it is handed and returns; the runner
owns the transaction boundary (commit on success, rollback on failure). Jobs
must NOT call ``session.commit()`` / ``session.rollback()`` themselves — see
``app.pipeline.runner`` for the full contract.
"""

from __future__ import annotations

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.pipeline.sources import tpex, twse


def fetch_tw_quotes(session: Session) -> None:
    """Fetch TWSE (上市) + TPEx (上櫃) daily closes into ``quotes_daily``.

    Flow: ``twse.fetch()`` + ``tpex.fetch()`` → each ``parse()`` → merge →
    keep only tickers already present in ``companies`` → upsert one row per
    ``(ticker, date)``.

    Rows whose parsed ``date`` is None (missing/malformed ROC date) are skipped
    with a warning. date 為 None 的列一律跳過（不 fallback 今日）——真實來源皆自帶
    Date 欄，異常時跳過比標錯日期安全。A source fetch failure (``SourceFetchError``)
    is left to propagate so the runner can retry — it is not swallowed here.

    Contract: stages changes only; the runner commits/rolls back.
    """
    # Fetch is intentionally NOT wrapped: a SourceFetchError must reach the
    # runner so the run is retried/recorded, per the job contract.
    rows = twse.parse(twse.fetch()) + tpex.parse(tpex.fetch())

    known: set[str] = set(session.scalars(select(models.Company.ticker)).all())

    upserted = 0
    skipped_date = 0
    for row in rows:
        ticker = row["ticker"]
        if ticker not in known:
            continue
        date = row["date"]
        if date is None:
            skipped_date += 1
            logger.warning(
                "fetch_tw_quotes: skip {} — 缺少有效日期（date is None）", ticker
            )
            continue

        quote = session.get(models.QuoteDaily, (ticker, date))
        if quote is None:
            quote = models.QuoteDaily(ticker=ticker, date=date)
            session.add(quote)
        quote.open = row["open"]
        quote.high = row["high"]
        quote.low = row["low"]
        quote.close = row["close"]
        quote.volume = row["volume"]
        quote.change_pct = row["change_pct"]
        upserted += 1

    logger.info(
        "fetch_tw_quotes: upserted {} 檔收盤（skipped {} 檔缺日期）",
        upserted,
        skipped_date,
    )
