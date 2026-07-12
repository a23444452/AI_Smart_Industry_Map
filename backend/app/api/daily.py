"""GET /api/daily 每日焦點聚合，與 GET /api/daily/announcements 單日重大訊息.

/api/daily 一次回傳跑馬燈指數、全市場三大法人與信用交易餘額（各取最新一日）、
漲跌幅榜（day/week/month）與近 7 個有公告的台北日期。市場統計的 ``unit``／``item``
以來源原名原樣輸出，顯示映射由前端負責。

時間語意：所有 ``published_at``／``fetched_at`` 為 naive UTC（見 app.db.base），
輸出一律經 ``to_utc_iso`` 帶 ``Z``。announcements 的 ``date`` 參數語意為**台北日期**，
換算為 UTC 半開區間 [date 00:00 台北, date+1 00:00 台北) 過濾。
"""

from datetime import UTC, date as date_type, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel
from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.api.queries import period_change, quotes_by_ticker
from app.api.serializers import to_utc_iso
from app.db.models import (
    Company,
    IndexSnapshot,
    MarginBalance,
    MarketFlow,
    MopsAnnouncement,
    QuoteDaily,
)
from app.pipeline.sources.yahoo_indices import SYMBOLS as INDEX_SYMBOLS

router = APIRouter(tags=["daily"])

TAIPEI = ZoneInfo("Asia/Taipei")

# 漲跌幅榜週／月報酬的交易日偏移（與 topic detail treemap 同口徑）。
WEEK_OFFSET = 5
MONTH_OFFSET = 21
# 每個週期取降冪 top N。
MOVERS_TOP_N = 30
# announcements_dates 取最近幾個有公告的台北日期。
ANNOUNCEMENTS_DATE_LIMIT = 7


# ── Pydantic response models ──────────────────────────────────────────────
class IndexRow(BaseModel):
    symbol: str
    name: str
    price: float
    change: float | None
    change_pct: float | None
    fetched_at: str | None


class FlowRow(BaseModel):
    unit: str
    buy: int | None
    sell: int | None
    net: int | None


class MarketFlows(BaseModel):
    date: str | None
    rows: list[FlowRow]


class MarginRow(BaseModel):
    item: str
    buy: int | None
    sell: int | None
    prev_balance: int | None
    today_balance: int | None


class Margin(BaseModel):
    date: str | None
    rows: list[MarginRow]


class MoverItem(BaseModel):
    ticker: str
    name: str
    close: float | None
    change_pct: float | None


class Movers(BaseModel):
    day: list[MoverItem]
    week: list[MoverItem]
    month: list[MoverItem]


class DailyResponse(BaseModel):
    indices: list[IndexRow]
    market_flows: MarketFlows
    margin: Margin
    movers: Movers
    announcements_dates: list[str]


class AnnouncementItem(BaseModel):
    ticker: str
    name: str
    category: str
    title: str
    published_at: str


# ── builders ──────────────────────────────────────────────────────────────
def _build_indices(session: Session) -> list[IndexRow]:
    """指數現值，依 SYMBOLS 定義順序；未列於 SYMBOLS 者排最後（依 symbol）。"""
    order = {sym: i for i, sym in enumerate(INDEX_SYMBOLS)}
    snapshots = session.execute(select(IndexSnapshot)).scalars().all()
    snapshots = sorted(
        snapshots, key=lambda s: (order.get(s.symbol, len(order)), s.symbol)
    )
    return [
        IndexRow(
            symbol=s.symbol,
            name=s.name,
            price=s.price,
            change=s.change,
            change_pct=s.change_pct,
            fetched_at=to_utc_iso(s.fetched_at),
        )
        for s in snapshots
    ]


def _build_market_flows(session: Session) -> MarketFlows:
    """最新一日全市場三大法人買賣金額；空表 → date null、rows []。"""
    max_date = session.execute(select(func.max(MarketFlow.date))).scalar_one()
    if max_date is None:
        return MarketFlows(date=None, rows=[])
    stmt = (
        select(MarketFlow)
        .where(MarketFlow.date == max_date)
        .order_by(MarketFlow.unit)
    )
    rows = [
        FlowRow(unit=r.unit, buy=r.buy, sell=r.sell, net=r.net)
        for r in session.execute(stmt).scalars().all()
    ]
    return MarketFlows(date=max_date, rows=rows)


def _build_margin(session: Session) -> Margin:
    """最新一日全市場信用交易餘額；空表 → date null、rows []。"""
    max_date = session.execute(select(func.max(MarginBalance.date))).scalar_one()
    if max_date is None:
        return Margin(date=None, rows=[])
    stmt = (
        select(MarginBalance)
        .where(MarginBalance.date == max_date)
        .order_by(MarginBalance.item)
    )
    rows = [
        MarginRow(
            item=r.item,
            buy=r.buy,
            sell=r.sell,
            prev_balance=r.prev_balance,
            today_balance=r.today_balance,
        )
        for r in session.execute(stmt).scalars().all()
    ]
    return Margin(date=max_date, rows=rows)


def _build_movers(session: Session) -> Movers:
    """universe＝quotes_daily 全部 distinct ticker；day/week/month 各自降冪 top 30、null 排除。

    day＝最新日 change_pct（round 2），week/month＝5/21 交易日 offset 報酬。name 取自
    companies；quotes-only ticker（無對應 company）退回以 ticker 為 name。
    """
    tickers = [
        t for (t,) in session.execute(select(distinct(QuoteDaily.ticker))).all()
    ]
    if not tickers:
        return Movers(day=[], week=[], month=[])

    names = dict(
        session.execute(
            select(Company.ticker, Company.name).where(Company.ticker.in_(tickers))
        ).all()
    )
    quotes = quotes_by_ticker(session, tickers)

    def rank(kind: str) -> list[MoverItem]:
        items: list[MoverItem] = []
        for ticker in tickers:
            rows = quotes.get(ticker, [])
            if not rows:
                continue
            if kind == "day":
                raw = rows[0].change_pct
                change = None if raw is None else round(raw, 2)
            elif kind == "week":
                change = period_change(rows, WEEK_OFFSET)
            else:  # month
                change = period_change(rows, MONTH_OFFSET)
            if change is None:  # null 排除
                continue
            items.append(
                MoverItem(
                    ticker=ticker,
                    name=names.get(ticker, ticker),
                    close=rows[0].close,
                    change_pct=change,
                )
            )
        items.sort(key=lambda m: m.change_pct, reverse=True)
        return items[:MOVERS_TOP_N]

    return Movers(day=rank("day"), week=rank("week"), month=rank("month"))


def _taipei_date(dt: datetime) -> date_type:
    """naive UTC datetime → 台北日曆日。"""
    return dt.replace(tzinfo=UTC).astimezone(TAIPEI).date()


def _build_announcements_dates(session: Session) -> list[str]:
    """mops_announcements 依 published_at（轉台北日期）distinct 降冪取 7 天。"""
    published = session.execute(select(MopsAnnouncement.published_at)).scalars().all()
    dates = {_taipei_date(dt).isoformat() for dt in published}
    return sorted(dates, reverse=True)[:ANNOUNCEMENTS_DATE_LIMIT]


@router.get("/daily", response_model=DailyResponse)
def get_daily(request: Request) -> DailyResponse:
    engine = request.app.state.engine
    with Session(engine) as session:
        return DailyResponse(
            indices=_build_indices(session),
            market_flows=_build_market_flows(session),
            margin=_build_margin(session),
            movers=_build_movers(session),
            announcements_dates=_build_announcements_dates(session),
        )


@router.get("/daily/announcements", response_model=list[AnnouncementItem])
def get_daily_announcements(
    request: Request,
    date: date_type = Query(..., description="台北日期 YYYY-MM-DD"),
    category: str | None = Query(
        None, description="公告分類篩選（如「澄清回應」）；未帶回全部分類"
    ),
) -> list[AnnouncementItem]:
    # 台北日 [date 00:00, date+1 00:00) → naive UTC 半開區間過濾（published_at 存 naive UTC）。
    start_taipei = datetime.combine(date, time.min, tzinfo=TAIPEI)
    start_utc = start_taipei.astimezone(UTC).replace(tzinfo=None)
    end_utc = (start_taipei + timedelta(days=1)).astimezone(UTC).replace(tzinfo=None)

    stmt = (
        select(MopsAnnouncement)
        .where(
            MopsAnnouncement.published_at >= start_utc,
            MopsAnnouncement.published_at < end_utc,
        )
        .order_by(MopsAnnouncement.published_at.desc())
    )
    if category is not None:
        stmt = stmt.where(MopsAnnouncement.category == category)
    engine = request.app.state.engine
    with Session(engine) as session:
        return [
            AnnouncementItem(
                ticker=a.ticker,
                name=a.name,
                category=a.category,
                title=a.title,
                published_at=to_utc_iso(a.published_at),
            )
            for a in session.execute(stmt).scalars().all()
        ]
