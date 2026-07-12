"""GET /api/topics — topic cards for a market tab plus a top-3 movers ranking.

Each card carries a distinct-ticker ``company_count`` and ``change_pct_avg`` —
the mean of every member's latest-day ``change_pct`` (NULLs skipped). Both are
computed in a single grouped query (no per-topic N+1); ``rank`` is derived in
Python from the already-materialised cards.
"""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.queries import flows_by_ticker, period_change, quotes_by_ticker
from app.api.serializers import to_utc_iso
from app.db.models import (
    Company,
    InstitutionalFlow,
    PipelineRun,
    QuoteDaily,
    Topic,
    TopicCompany,
)

router = APIRouter(tags=["topics"])

Market = Literal["tw", "us", "jp", "chain", "etf"]
Direction = Literal["up", "down"]

# 籌碼訊號視窗：每檔取最新 5 筆法人買賣超彙總。
CHIP_WINDOW_DAYS = 5
# treemap 週／月報酬的交易日偏移（以該 ticker 實際存在的交易日排序計算）。
WEEK_OFFSET = 5
MONTH_OFFSET = 21
# quotes_updated_at 綁定的行情 job 名稱（見 app.pipeline.scheduler）。
QUOTES_JOB_NAME = "fetch_tw_quotes"

_NOT_FOUND_BODY = {"error": {"code": "not_found", "message": "找不到此題材"}}


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


# ── GET /api/topics/{slug} — 題材詳情 ─────────────────────────────────────


class TreemapItem(BaseModel):
    ticker: str
    name: str
    change_pct: float | None


class Treemap(BaseModel):
    day: list[TreemapItem]
    week: list[TreemapItem]
    month: list[TreemapItem]


class ChipSignals(BaseModel):
    window_days: int
    total: int
    foreign_buy: int
    trust_buy: int
    # major（自營商）暫不計算，恆為 null——切片 4 再定義口徑。
    major_buy: int | None
    updated_at: str | None


class TopicDetail(BaseModel):
    slug: str
    title: str
    description: str | None
    metrics: dict | None
    verified_at: str | None
    treemap: Treemap
    chip_signals: ChipSignals
    quotes_updated_at: str | None


def _distinct_members(session: Session, slug: str) -> list[tuple[str, str]]:
    """該題材的 distinct (ticker, name)，依 ticker 排序（同一 ticker 跨分類只列一次）。"""
    stmt = (
        select(TopicCompany.ticker, Company.name)
        .join(Company, Company.ticker == TopicCompany.ticker)
        .where(TopicCompany.topic_slug == slug)
        .distinct()
        .order_by(TopicCompany.ticker)
    )
    return [(row.ticker, row.name) for row in session.execute(stmt).all()]


def _build_treemap(
    members: list[tuple[str, str]], quotes: dict[str, list]
) -> Treemap:
    def items(kind: str) -> list[TreemapItem]:
        out = []
        for ticker, name in members:
            rows = quotes.get(ticker, [])
            if kind == "day":
                # 與 week/month 一致：伺服端統一 round 2，UI 不必處理浮點殘差。
                raw = rows[0].change_pct if rows else None
                change = None if raw is None else round(raw, 2)
            elif kind == "week":
                change = period_change(rows, WEEK_OFFSET)
            else:  # month
                change = period_change(rows, MONTH_OFFSET)
            out.append(TreemapItem(ticker=ticker, name=name, change_pct=change))
        return out

    return Treemap(day=items("day"), week=items("week"), month=items("month"))


def _build_chip_signals(
    members: list[tuple[str, str]],
    flows: dict[str, list[InstitutionalFlow]],
) -> ChipSignals:
    foreign_buy = 0
    trust_buy = 0
    max_date: str | None = None
    for ticker, _ in members:
        member_flows = flows.get(ticker, [])
        recent = member_flows[:CHIP_WINDOW_DAYS]
        if sum((f.foreign_net or 0) for f in recent) > 0:
            foreign_buy += 1
        if sum((f.trust_net or 0) for f in recent) > 0:
            trust_buy += 1
        for flow in member_flows:
            if max_date is None or flow.date > max_date:
                max_date = flow.date

    updated_at = (
        to_utc_iso(datetime.fromisoformat(max_date)) if max_date else None
    )
    return ChipSignals(
        window_days=CHIP_WINDOW_DAYS,
        total=len(members),
        foreign_buy=foreign_buy,
        trust_buy=trust_buy,
        major_buy=None,
        updated_at=updated_at,
    )


def _quotes_updated_at(session: Session) -> str | None:
    """最新一次 fetch_tw_quotes 成功 run 的 finished_at（帶 Z）；無紀錄 → None。"""
    stmt = (
        select(PipelineRun.finished_at)
        .where(
            PipelineRun.job_name == QUOTES_JOB_NAME,
            PipelineRun.status == "success",
        )
        .order_by(PipelineRun.id.desc())
        .limit(1)
    )
    row = session.execute(stmt).first()
    return to_utc_iso(row[0]) if row is not None else None


@router.get(
    "/topics/{slug}",
    response_model=TopicDetail,
    responses={
        404: {
            "description": "題材不存在",
            "content": {
                "application/json": {
                    "example": {
                        "error": {
                            "code": "not_found",
                            "message": "找不到此題材",
                        }
                    }
                }
            },
        }
    },
)
def get_topic_detail(slug: str, request: Request):
    engine = request.app.state.engine
    with Session(engine) as session:
        topic = session.get(Topic, slug)
        if topic is None:
            # 統一錯誤格式（與 topic map、全域 500 handler 一致）；直接回
            # JSONResponse，不經 response_model 序列化。
            return JSONResponse(status_code=404, content=_NOT_FOUND_BODY)

        members = _distinct_members(session, slug)
        tickers = [ticker for ticker, _ in members]
        quotes = quotes_by_ticker(session, tickers)
        flows = flows_by_ticker(session, tickers)

        return TopicDetail(
            slug=topic.slug,
            title=topic.title,
            description=topic.description,
            metrics=topic.metrics,
            verified_at=topic.verified_at,
            treemap=_build_treemap(members, quotes),
            chip_signals=_build_chip_signals(members, flows),
            quotes_updated_at=_quotes_updated_at(session),
        )
