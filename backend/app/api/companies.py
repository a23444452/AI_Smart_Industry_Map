"""companies API：清單、詳情、圖表三端點.

- ``GET /api/companies`` — 可搜尋（ticker 前綴 OR name 包含）、可依 topic 篩選、
  分頁（page_size 上限 100）的公司清單。每列帶各表最新一筆的
  close/change_pct/per/revenue_yoy（皆 nullable）與所屬 topic slug 清單；
  ``topics_facets`` 恆為全部 topics（供前端下拉，不隨篩選變動）。查詢筆數固定
  （companies 分頁一次、topic slugs 一次、quotes/per/fundamentals 各最新一次），
  無 per-row N+1。

- ``GET /api/companies/{ticker}`` — 單檔詳情：最新報價（close/change_pct/volume）、
  change＝最新兩交易日 close 差（不足→null）、最新 per/pbr/dividend_yield、最新
  月營收與集保大戶（缺→null）、所屬 topics（{slug,title}）、徽章與
  quotes_updated_at（重用 ``queries.badges_for``／``queries.quotes_updated_at``，
  與 topic_map／topics 單一來源）。

「各表最新一筆」重用 ``queries.latest_rows``，帶時間下界（日／週頻 60 日曆日、
月頻 12 個月）——與 queries.py 慣例一致，避免歷史累積後的無界掃描。

- ``GET /api/companies/{ticker}/charts/{kind}`` — kind ∈ kline/per_river/
  institutional/holders（Literal，未知→422）；ticker 不存在→404，有 ticker 無
  資料→items []。per_river 河流圖分位以該 ticker per_daily 全期 PER（None/0 排除）
  計算，樣本 <10 筆則全部 band null。

分位數採 numpy-free 自寫 R-7 線性插值（``_quantile``）：pos＝q×(n−1)，於相鄰兩點
線性內插。選 R-7 是因其為 numpy.percentile 預設法，且可手算對照（見單元測試）。
"""

import math
from typing import Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.api.queries import (
    FUNDAMENTALS_LOOKBACK_MONTHS,
    QUOTES_LOOKBACK_DAYS,
    badges_for,
    cutoff_date,
    cutoff_month,
    latest_rows,
    quotes_updated_at,
)
from app.db.models import (
    Company,
    Fundamental,
    InstitutionalFlow,
    MajorHolder,
    PerDaily,
    QuoteDaily,
    Topic,
    TopicCompany,
)

router = APIRouter(tags=["companies"])

# per_river 河流圖分位所需最小 PER 樣本數；不足則全部 band 輸出 null。
MIN_PER_SAMPLES = 10
# per_river 河流圖分位點（百分位）。
RIVER_PERCENTILES = (10, 25, 50, 75, 90)
# institutional 圖表取最近幾個交易日。
INSTITUTIONAL_RECENT_DAYS = 60

_NOT_FOUND_BODY = {"error": {"code": "not_found", "message": "找不到此公司"}}
_NOT_FOUND_RESPONSES = {
    404: {
        "description": "公司不存在",
        "content": {
            "application/json": {
                "example": _NOT_FOUND_BODY,
            }
        },
    }
}


# ── 分位數（numpy-free R-7 線性插值）─────────────────────────────────────
def _quantile(sorted_values: list[float], q: float) -> float:
    """已排序序列的第 ``q`` 分位（q∈[0,1]），R-7 線性插值。

    pos＝q×(n−1)，落在相鄰索引間則線性內插；空序列以外均有定義（呼叫端保證非空）。
    R-7 為 numpy.percentile 預設法，且可手算對照（見單元測試）。
    """
    n = len(sorted_values)
    if n == 1:
        return sorted_values[0]
    pos = q * (n - 1)
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return sorted_values[lo]
    frac = pos - lo
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * frac


# ── 清單端點 ────────────────────────────────────────────────────────────
class CompanyListItem(BaseModel):
    ticker: str
    name: str
    market: str
    topics: list[str]
    close: float | None
    change_pct: float | None
    per: float | None
    revenue_yoy: float | None


class TopicFacet(BaseModel):
    slug: str
    title: str


class CompanyListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[CompanyListItem]
    topics_facets: list[TopicFacet]


def _topics_by_ticker(session: Session, tickers: list[str]) -> dict[str, list[str]]:
    """各 ticker 所屬 topic slug（distinct、升冪）。"""
    if not tickers:
        return {}
    stmt = (
        select(TopicCompany.ticker, TopicCompany.topic_slug)
        .where(TopicCompany.ticker.in_(tickers))
        .distinct()
        .order_by(TopicCompany.topic_slug)
    )
    grouped: dict[str, list[str]] = {}
    for ticker, slug in session.execute(stmt).all():
        grouped.setdefault(ticker, []).append(slug)
    return grouped


def _all_facets(session: Session) -> list[TopicFacet]:
    """全部 topics（供前端下拉），依 slug 升冪；不隨清單篩選變動。"""
    stmt = select(Topic.slug, Topic.title).order_by(Topic.slug)
    return [TopicFacet(slug=s, title=t) for s, t in session.execute(stmt).all()]


@router.get("/companies", response_model=CompanyListResponse)
def list_companies(
    request: Request,
    query: str = Query("", description="ticker 前綴或 name 包含"),
    topic: str = Query("", description="題材 slug 篩選；空＝不篩"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> CompanyListResponse:
    engine = request.app.state.engine
    with Session(engine) as session:
        base = select(Company)
        if query:
            base = base.where(
                Company.ticker.like(f"{query}%") | Company.name.contains(query)
            )
        if topic:
            member_tickers = (
                select(distinct(TopicCompany.ticker))
                .where(TopicCompany.topic_slug == topic)
                .scalar_subquery()
            )
            base = base.where(Company.ticker.in_(member_tickers))

        total = session.execute(
            select(func.count()).select_from(base.subquery())
        ).scalar_one()

        page_stmt = (
            base.order_by(Company.ticker)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        companies = session.execute(page_stmt).scalars().all()
        tickers = [c.ticker for c in companies]

        topics_map = _topics_by_ticker(session, tickers)
        day_cutoff = cutoff_date(QUOTES_LOOKBACK_DAYS)
        quotes = latest_rows(session, QuoteDaily, QuoteDaily.date, tickers, day_cutoff)
        pers = latest_rows(session, PerDaily, PerDaily.date, tickers, day_cutoff)
        funds = latest_rows(
            session,
            Fundamental,
            Fundamental.month,
            tickers,
            cutoff_month(FUNDAMENTALS_LOOKBACK_MONTHS),
        )

        items: list[CompanyListItem] = []
        for c in companies:
            q = quotes.get(c.ticker)
            items.append(
                CompanyListItem(
                    ticker=c.ticker,
                    name=c.name,
                    market=c.market,
                    topics=topics_map.get(c.ticker, []),
                    close=q.close if q else None,
                    change_pct=(
                        None
                        if q is None or q.change_pct is None
                        else round(q.change_pct, 2)
                    ),
                    per=pers[c.ticker].per if c.ticker in pers else None,
                    revenue_yoy=funds[c.ticker].yoy if c.ticker in funds else None,
                )
            )

        return CompanyListResponse(
            total=total,
            page=page,
            page_size=page_size,
            items=items,
            topics_facets=_all_facets(session),
        )


# ── 詳情端點 ────────────────────────────────────────────────────────────
class LatestRevenue(BaseModel):
    month: str
    revenue: int | None
    yoy: float | None


class MajorHolderInfo(BaseModel):
    week: str
    ratio_400up: float


class CompanyDetail(BaseModel):
    ticker: str
    name: str
    market: str
    close: float | None
    change: float | None
    change_pct: float | None
    volume: int | None
    topics: list[TopicFacet]
    badges: list[str]
    per: float | None
    pbr: float | None
    dividend_yield: float | None
    latest_revenue: LatestRevenue | None
    major_holder: MajorHolderInfo | None
    quotes_updated_at: str | None


def _company_topics(session: Session, ticker: str) -> list[TopicFacet]:
    """該 ticker 所屬 topics（{slug,title}，distinct、依 slug 升冪）。"""
    stmt = (
        select(Topic.slug, Topic.title)
        .join(TopicCompany, TopicCompany.topic_slug == Topic.slug)
        .where(TopicCompany.ticker == ticker)
        .distinct()
        .order_by(Topic.slug)
    )
    return [TopicFacet(slug=s, title=t) for s, t in session.execute(stmt).all()]


@router.get(
    "/companies/{ticker}",
    response_model=CompanyDetail,
    responses=_NOT_FOUND_RESPONSES,
)
def get_company(ticker: str, request: Request):
    engine = request.app.state.engine
    with Session(engine) as session:
        company = session.get(Company, ticker)
        if company is None:
            return JSONResponse(status_code=404, content=_NOT_FOUND_BODY)

        # 最新兩交易日報價：close/volume/change_pct 取最新，change＝最新−前一日。
        two = (
            session.execute(
                select(QuoteDaily)
                .where(QuoteDaily.ticker == ticker)
                .order_by(QuoteDaily.date.desc())
                .limit(2)
            )
            .scalars()
            .all()
        )
        latest_q = two[0] if two else None
        close = latest_q.close if latest_q else None
        change = None
        if len(two) == 2 and two[0].close is not None and two[1].close is not None:
            change = round(two[0].close - two[1].close, 2)

        # 週頻 TDCC 大戶資料同用 60 日曆日下界（覆蓋約 8 週，綽綽有餘）。
        day_cutoff = cutoff_date(QUOTES_LOOKBACK_DAYS)
        per_row = latest_rows(
            session, PerDaily, PerDaily.date, [ticker], day_cutoff
        ).get(ticker)
        fund_row = latest_rows(
            session,
            Fundamental,
            Fundamental.month,
            [ticker],
            cutoff_month(FUNDAMENTALS_LOOKBACK_MONTHS),
        ).get(ticker)
        hold_row = latest_rows(
            session, MajorHolder, MajorHolder.week, [ticker], day_cutoff
        ).get(ticker)

        latest_flow = (
            session.execute(
                select(InstitutionalFlow)
                .where(InstitutionalFlow.ticker == ticker)
                .order_by(InstitutionalFlow.date.desc())
                .limit(1)
            )
            .scalars()
            .first()
        )

        return CompanyDetail(
            ticker=company.ticker,
            name=company.name,
            market=company.market,
            close=close,
            change=change,
            change_pct=(
                None
                if latest_q is None or latest_q.change_pct is None
                else round(latest_q.change_pct, 2)
            ),
            volume=latest_q.volume if latest_q else None,
            topics=_company_topics(session, ticker),
            badges=badges_for(company.has_futures, latest_flow),
            per=per_row.per if per_row else None,
            pbr=per_row.pbr if per_row else None,
            dividend_yield=per_row.dividend_yield if per_row else None,
            latest_revenue=(
                LatestRevenue(
                    month=fund_row.month, revenue=fund_row.revenue, yoy=fund_row.yoy
                )
                if fund_row
                else None
            ),
            major_holder=(
                MajorHolderInfo(week=hold_row.week, ratio_400up=hold_row.ratio_400up)
                if hold_row
                else None
            ),
            quotes_updated_at=quotes_updated_at(session),
        )


# ── 圖表端點 ────────────────────────────────────────────────────────────
class KlineItem(BaseModel):
    date: str
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: int | None


class PerRiverItem(BaseModel):
    date: str
    close: float | None
    band_p10: float | None
    band_p25: float | None
    band_p50: float | None
    band_p75: float | None
    band_p90: float | None


class InstitutionalItem(BaseModel):
    date: str
    foreign_net: int | None
    trust_net: int | None
    dealer_net: int | None


class HoldersItem(BaseModel):
    week: str
    ratio_400up: float


ChartKind = Literal["kline", "per_river", "institutional", "holders"]


def _kline(session: Session, ticker: str) -> list[KlineItem]:
    """quotes_daily 全期升冪。"""
    stmt = (
        select(QuoteDaily)
        .where(QuoteDaily.ticker == ticker)
        .order_by(QuoteDaily.date)
    )
    return [
        KlineItem(
            date=q.date,
            open=q.open,
            high=q.high,
            low=q.low,
            close=q.close,
            volume=q.volume,
        )
        for q in session.execute(stmt).scalars().all()
    ]


def _per_river(session: Session, ticker: str) -> list[PerRiverItem]:
    """per_daily 全期升冪；band 以全期 PER（None/0 排除）分位×當日 EPS_ttm。

    分位樣本＝該 ticker 全期有效 PER（None/0 排除）；不足 ``MIN_PER_SAMPLES`` 則
    所有 band null。逐日：EPS_ttm＝當日 close÷當日 PER（close 取 quotes 同日；close
    缺、PER None/0 → 該日 band 全 null）；band_pXX＝EPS_ttm×PER 分位。
    """
    per_rows = (
        session.execute(
            select(PerDaily)
            .where(PerDaily.ticker == ticker)
            .order_by(PerDaily.date)
        )
        .scalars()
        .all()
    )
    if not per_rows:
        return []

    # 同期 quotes close，依 date 對照。
    close_by_date = dict(
        session.execute(
            select(QuoteDaily.date, QuoteDaily.close).where(
                QuoteDaily.ticker == ticker
            )
        ).all()
    )

    sample = sorted(r.per for r in per_rows if r.per not in (None, 0))
    bands = None
    if len(sample) >= MIN_PER_SAMPLES:
        bands = {p: _quantile(sample, p / 100) for p in RIVER_PERCENTILES}

    items: list[PerRiverItem] = []
    for r in per_rows:
        close = close_by_date.get(r.date)
        # EPS_ttm 需要有效 close 與有效 PER；任一缺 → 該日 band 全 null。
        eps = None
        if bands is not None and close is not None and r.per not in (None, 0):
            eps = close / r.per

        def band(p: int) -> float | None:
            if eps is None:
                return None
            return round(eps * bands[p], 2)

        items.append(
            PerRiverItem(
                date=r.date,
                close=close,
                band_p10=band(10),
                band_p25=band(25),
                band_p50=band(50),
                band_p75=band(75),
                band_p90=band(90),
            )
        )
    return items


def _institutional(session: Session, ticker: str) -> list[InstitutionalItem]:
    """institutional_flows 近 60 交易日升冪（先降冪取 60，再反轉）。"""
    recent = (
        session.execute(
            select(InstitutionalFlow)
            .where(InstitutionalFlow.ticker == ticker)
            .order_by(InstitutionalFlow.date.desc())
            .limit(INSTITUTIONAL_RECENT_DAYS)
        )
        .scalars()
        .all()
    )
    return [
        InstitutionalItem(
            date=f.date,
            foreign_net=f.foreign_net,
            trust_net=f.trust_net,
            dealer_net=f.dealer_net,
        )
        for f in reversed(recent)
    ]


def _holders(session: Session, ticker: str) -> list[HoldersItem]:
    """major_holders 全期升冪。"""
    stmt = (
        select(MajorHolder)
        .where(MajorHolder.ticker == ticker)
        .order_by(MajorHolder.week)
    )
    return [
        HoldersItem(week=h.week, ratio_400up=h.ratio_400up)
        for h in session.execute(stmt).scalars().all()
    ]


@router.get(
    "/companies/{ticker}/charts/{kind}",
    responses=_NOT_FOUND_RESPONSES,
)
def get_company_chart(ticker: str, kind: ChartKind, request: Request):
    engine = request.app.state.engine
    with Session(engine) as session:
        if session.get(Company, ticker) is None:
            return JSONResponse(status_code=404, content=_NOT_FOUND_BODY)

        builders = {
            "kline": _kline,
            "per_river": _per_river,
            "institutional": _institutional,
            "holders": _holders,
        }
        items = builders[kind](session, ticker)
        return {"items": [it.model_dump() for it in items]}
