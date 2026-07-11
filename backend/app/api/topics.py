"""GET /api/topics — topic cards for a market tab plus a top-3 movers ranking.

Each card carries a distinct-ticker ``company_count`` and ``change_pct_avg`` —
the mean of every member's latest-day ``change_pct`` (NULLs skipped). Both are
computed in a single grouped query (no per-topic N+1); ``rank`` is derived in
Python from the already-materialised cards.
"""

from typing import Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import QuoteDaily, Topic, TopicCompany

router = APIRouter(tags=["topics"])

Market = Literal["tw", "us", "jp", "chain", "etf"]
Direction = Literal["up", "down"]


class TopicSummary(BaseModel):
    slug: str
    title: str
    description: str | None
    market_tab: str
    company_count: int
    verified_at: str | None
    change_pct_avg: float | None


class TopicsResponse(BaseModel):
    topics: list[TopicSummary]
    rank: list[TopicSummary]


def _latest_quote_subquery():
    """One row per ticker: its ``change_pct`` on that ticker's newest date.

    ``date`` is stored as ISO ``YYYY-MM-DD`` so MAX() picks the latest day
    lexically. Built as a join of ``quotes_daily`` to its own per-ticker max
    date so ties (there are none — date is part of the PK) can't fan out.
    """
    latest_date = (
        select(
            QuoteDaily.ticker.label("ticker"),
            func.max(QuoteDaily.date).label("max_date"),
        )
        .group_by(QuoteDaily.ticker)
        .subquery()
    )
    return (
        select(
            QuoteDaily.ticker.label("ticker"),
            QuoteDaily.change_pct.label("change_pct"),
        )
        .join(
            latest_date,
            (QuoteDaily.ticker == latest_date.c.ticker)
            & (QuoteDaily.date == latest_date.c.max_date),
        )
        .subquery()
    )


def _query_topics(session: Session, market: str) -> list[TopicSummary]:
    # Distinct (topic, ticker) so a ticker listed under several categories is
    # counted once — company_count must be DISTINCT tickers, not row count.
    members = (
        select(
            TopicCompany.topic_slug.label("slug"),
            TopicCompany.ticker.label("ticker"),
        )
        .distinct()
        .subquery()
    )
    latest = _latest_quote_subquery()

    stmt = (
        select(
            Topic.slug,
            Topic.title,
            Topic.description,
            Topic.market_tab,
            Topic.verified_at,
            func.count(func.distinct(members.c.ticker)).label("company_count"),
            # AVG skips NULL change_pct automatically → members with a NULL
            # latest quote, or no quotes at all (LEFT JOIN → NULL), drop out.
            func.avg(latest.c.change_pct).label("change_pct_avg"),
        )
        .select_from(Topic)
        .outerjoin(members, members.c.slug == Topic.slug)
        .outerjoin(latest, latest.c.ticker == members.c.ticker)
        .where(Topic.market_tab == market)
        .group_by(Topic.slug)
        .order_by(Topic.slug)
    )

    return [
        TopicSummary(
            slug=row.slug,
            title=row.title,
            description=row.description,
            market_tab=row.market_tab,
            company_count=row.company_count,
            verified_at=row.verified_at,
            # Server-side rounding to 2 decimals fixes the API contract — the
            # UI renders "X.XX%" and must not depend on float artifacts.
            change_pct_avg=(
                None if row.change_pct_avg is None else round(row.change_pct_avg, 2)
            ),
        )
        for row in session.execute(stmt).all()
    ]


def _rank(topics: list[TopicSummary], direction: str) -> list[TopicSummary]:
    # Rank only over topics with a defined average; a market with no quote data
    # yields an empty ranking rather than surfacing null-avg cards.
    ranked = [t for t in topics if t.change_pct_avg is not None]
    ranked.sort(key=lambda t: t.change_pct_avg, reverse=direction == "up")
    return ranked[:3]


@router.get("/topics", response_model=TopicsResponse)
def get_topics(
    request: Request,
    market: Market = Query(...),
    direction: Direction = Query("up"),
) -> TopicsResponse:
    engine = request.app.state.engine
    with Session(engine) as session:
        topics = _query_topics(session, market)
    return TopicsResponse(topics=topics, rank=_rank(topics, direction))
