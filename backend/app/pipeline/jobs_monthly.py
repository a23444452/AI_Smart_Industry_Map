"""低頻/基本面類 jobs — 月營收基本面與集保大戶持股.

Despite the「monthly」name these are the *slow-moving* pipeline jobs, driven on
a lighter cadence than the daily-focus / quotes fetches:

* :func:`fetch_fundamentals` — 月營收 (上市 + 上櫃) → ``fundamentals``. Scheduled
  **daily** as a light poll: the monthly-revenue feed is a *progressive* snapshot
  of the current reporting month — late filers appear over the following days —
  so an idempotent upsert (two requests/day) keeps the table current without
  waiting for a month boundary.
* :func:`fetch_tdcc` — 集保股權分散 (TDCC, weekly data) → ``major_holders``.
  Scheduled weekly (Saturday) since the feed only refreshes once a week.

Both obey the runner contract — they stage DB changes on the session they are
handed and return; the runner owns commit/rollback. Jobs must NOT call
``session.commit()`` / ``session.rollback()`` themselves (see
``app.pipeline.runner``).
"""

from __future__ import annotations

from loguru import logger
from sqlalchemy.orm import Session

from app.db import models
from app.pipeline.jobs import _known_tickers
from app.pipeline.sources import tdcc_holders, tpex_revenue, twse_revenue
from app.pipeline.sources._common import SourceFetchError


# --------------------------------------------------------------------------- #
# fetch_fundamentals — 月營收（上市 + 上櫃）→ fundamentals
# --------------------------------------------------------------------------- #


def _upsert_fundamentals(session: Session, rows: list[dict], known: set[str]) -> int:
    """Upsert neutral monthly-revenue dicts into ``fundamentals`` (ticker+month PK).

    Drops tickers not in ``known`` (feed is whole-market) and rows whose ``month``
    failed to parse (``month`` is part of the PK, a None PK is meaningless).
    Overwrites the existing ``(ticker, month)`` row so a late-corrected revenue
    figure supersedes the earlier snapshot. Returns rows written; shared by the
    上市 + 上櫃 legs of :func:`fetch_fundamentals`.
    """
    written = 0
    for row in rows:
        ticker = row["ticker"]
        if ticker not in known:
            continue
        month = row["month"]
        if month is None:
            continue  # 無法解析年月的列跳過（month 為複合 PK，不可為 None）
        rec = session.get(models.Fundamental, (ticker, month))
        if rec is None:
            rec = models.Fundamental(ticker=ticker, month=month)
            session.add(rec)
        rec.revenue = row["revenue"]
        rec.yoy = row["yoy"]
        written += 1
    return written


def fetch_fundamentals(session: Session) -> None:
    """Fetch 上市 + 上櫃 latest-month 營收 snapshots → upsert ``fundamentals``.

    Mirrors ``fetch_market_stats``'s two-source isolation: each feed is fetched +
    upserted under an **independent** try/except so one failing source neither
    aborts the other nor discards its already-staged rows — a single failure logs
    a warning and the run still succeeds on the source that worked; only when
    **both** raise ``SourceFetchError`` is the first re-raised so the runner
    records the run as failed.

    Rows are filtered to 收錄公司 and upserted on ``(ticker, month)`` (see
    :func:`_upsert_fundamentals`), so re-running as late filers appear simply
    overwrites in place.

    Contract: stages changes only; the runner commits/rolls back.
    """
    known = _known_tickers(session)
    listed_error: SourceFetchError | None = None
    otc_error: SourceFetchError | None = None
    listed_rows = otc_rows = 0

    try:
        listed = twse_revenue.parse(twse_revenue.fetch())
    except SourceFetchError as exc:
        listed_error = exc
        logger.warning("fetch_fundamentals: 上市月營收略過 — {}", exc)
    else:
        listed_rows = _upsert_fundamentals(session, listed, known)

    try:
        otc = tpex_revenue.parse(tpex_revenue.fetch())
    except SourceFetchError as exc:
        otc_error = exc
        logger.warning("fetch_fundamentals: 上櫃月營收略過 — {}", exc)
    else:
        otc_rows = _upsert_fundamentals(session, otc, known)

    if listed_error is not None and otc_error is not None:
        # 兩來源皆失敗才 raise（讓 runner 記 failed）；單一來源失敗則另一來源已
        # stage 的資料照常提交（與 fetch_market_stats / fetch_per 同策略）。
        raise listed_error
    logger.info(
        "fetch_fundamentals: fundamentals 上市 {} 列、上櫃 {} 列", listed_rows, otc_rows
    )


# --------------------------------------------------------------------------- #
# fetch_tdcc — 集保股權分散（TDCC 週資料）→ major_holders
# --------------------------------------------------------------------------- #


def fetch_tdcc(session: Session) -> None:
    """Fetch the weekly TDCC 集保 CSV → upsert ``major_holders`` (ticker+week PK).

    Single-source job: ``tdcc_holders.parse`` already filters to the ``wanted``
    set (收錄公司) and aggregates each ticker's 級距 into one ``(ratio_400up,
    holder_count)`` row per week, so no post-filter is needed here. A
    ``SourceFetchError`` (fetch failure or structural drift) is left to propagate
    so the runner records the run as failed and retries — it is not swallowed
    (there is no second source to fall back on, unlike the two-feed jobs).

    Contract: stages changes only; the runner commits/rolls back.
    """
    known = _known_tickers(session)
    # Fetch/parse intentionally NOT wrapped: a SourceFetchError must reach the
    # runner so the run is retried/recorded, per the single-source job contract.
    rows = tdcc_holders.parse(tdcc_holders.fetch(), known)

    written = 0
    for row in rows:
        ticker, week = row["ticker"], row["week"]
        rec = session.get(models.MajorHolder, (ticker, week))
        if rec is None:
            rec = models.MajorHolder(ticker=ticker, week=week)
            session.add(rec)
        rec.ratio_400up = row["ratio_400up"]
        rec.holder_count = row["holder_count"]
        written += 1
    logger.info("fetch_tdcc: major_holders upsert {} 檔", written)
