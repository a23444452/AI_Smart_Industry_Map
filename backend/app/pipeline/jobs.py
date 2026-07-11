"""Pipeline jobs — callables ``fn(session)`` driven by the runner.

A job stages DB changes on the session it is handed and returns; the runner
owns the transaction boundary (commit on success, rollback on failure). Jobs
must NOT call ``session.commit()`` / ``session.rollback()`` themselves — see
``app.pipeline.runner`` for the full contract.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.pipeline.sources import tpex, tpex_institutional, twse, twse_t86

_TAIPEI = ZoneInfo("Asia/Taipei")


def _taipei_today_iso() -> str:
    """今日（台北時區）ISO 日期。收盤後執行時當日資料已出。"""
    return datetime.now(_TAIPEI).date().isoformat()


def _known_tickers(session: Session) -> set[str]:
    return set(session.scalars(select(models.Company.ticker)).all())


def upsert_institutional_rows(
    session: Session, rows: list[dict], known: set[str]
) -> int:
    """Upsert neutral institutional-flow dicts into ``institutional_flows``.

    One row per ``(ticker, date)`` — parsed ``date`` is authoritative. Unknown
    tickers (not in ``known``) are dropped. Overwrites existing rows (fetch is
    the source of truth for a trading day) — the **opposite** of
    ``backfill_quotes``'s insert-only policy. Overwrite is safe only because the
    daily fetch and ``backfill_institutional`` funnel through the *same* parse
    with identical columns; should the daily fetch ever gain a column the
    backfill does not produce, this must switch to insert-only or the backfill
    would null that column out. Returns the number of rows written.

    Shared by :func:`fetch_institutional` and ``backfill_institutional`` so the
    daily fetch and the historical walk stay byte-identical in their persistence.
    """
    written = 0
    for row in rows:
        ticker = row["ticker"]
        if ticker not in known:
            continue
        date = row["date"]
        flow = session.get(models.InstitutionalFlow, (ticker, date))
        if flow is None:
            flow = models.InstitutionalFlow(ticker=ticker, date=date)
            session.add(flow)
        flow.foreign_net = row["foreign_net"]
        flow.trust_net = row["trust_net"]
        flow.dealer_net = row["dealer_net"]
        written += 1
    return written


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


def fetch_institutional(session: Session) -> None:
    """Fetch TWSE (T86) + TPEx daily three-institution net flows into
    ``institutional_flows``.

    Flow: ``twse_t86.fetch/parse`` + ``tpex_institutional.fetch/parse`` for
    「台北今日」 → merge → keep only tickers present in ``companies`` → upsert one
    row per ``(ticker, date)`` (parsed ``date`` — i.e. today — is authoritative).

    date 用台北今日：兩發 cron 於收盤後 16:10 / 17:10 執行，當日資料已出；假日
    來源 parse 回空，upsert 0 列，無害。A ``SourceFetchError`` from either source
    is left to propagate so the runner can retry — it is not swallowed here.

    Contract: stages changes only; the runner commits/rolls back.
    """
    date = _taipei_today_iso()
    # Fetch is intentionally NOT wrapped: a SourceFetchError must reach the
    # runner so the run is retried/recorded, per the job contract.
    rows = twse_t86.parse(twse_t86.fetch(date), date) + tpex_institutional.parse(
        tpex_institutional.fetch(date), date
    )
    written = upsert_institutional_rows(session, rows, _known_tickers(session))
    logger.info("fetch_institutional: upserted {} 檔法人買賣超（{}）", written, date)
