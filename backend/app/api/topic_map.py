"""GET /api/topics/{slug}/map — 產業鏈地圖（上中下游 × 分類 × 公司卡片）.

回傳結構完全依 ``Topic.chain_meta`` 骨架（level → categories 的 name/desc/
placeholder 與排序）逐格展開；公司歸屬自 ``topic_companies`` 讀入，並以
「chain_level ＋ 分類名稱」**同時**比對填入——避免跨 level 同名分類的錯配
（同名分類若落在不同 level，各自獨立，不共用成員）。placeholder 分類無公司，
一律 ``companies: []``。

注意：地圖是骨架驅動的——``chain_level`` 為 null、或其 (chain_level, category)
組合不存在於 ``chain_meta`` 的 ``topic_companies`` 成員，比對不到任何格子，
**不會顯示於地圖**（seed 匯入一律帶 chain_level，正常資料不會發生；此為資料
異常時的靜默行為，非錯誤）。

徽章口徑（重要，與總覽 ``chip_signals`` 不同）：
- ``有股票期貨`` ← ``companies.has_futures``。
- ``外資買超`` / ``投信買超`` ← 該 ticker ``institutional_flows`` 依 ``date``
  降冪**第一筆**的 ``foreign_net`` / ``trust_net`` > 0；無 flows → 無此二徽章；
  net ≤ 0 → 無。

  map 徽章刻意用「該 ticker 最新一筆 net>0」表達**當下動向**，而總覽
  ``chip_signals`` 用「近 5 交易日加總 > 0」表達**趨勢**——兩者口徑不同。之所以
  用「該 ticker 最新一筆」而非「全市場最新交易日」，是因為個股可能缺某日資料，
  以各檔自身最新有值日為準較穩健。

``close`` / ``change_pct`` ← ``quotes_daily`` 該 ticker 最新日（``change_pct``
round 2）；無 quotes → 兩者 ``null``。

查詢固定筆數（無 N+1）：topic get、topic_companies join companies（取 name/
has_futures/role/relevance）、最新 quotes、最新 flows 各一次，於 Python 組裝。
quotes/flows 重用共用模組 ``app.api.queries`` 的 ``quotes_by_ticker`` /
``flows_by_ticker``（含 60／21 日曆日下界，避免無界掃描；回傳按 ticker 分組、
date 降冪），map 只取每組降冪第一筆。
"""

from collections import defaultdict

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.queries import badges_for, flows_by_ticker, quotes_by_ticker
from app.db.models import Company, Topic, TopicCompany

router = APIRouter(tags=["topic-map"])

_NOT_FOUND_BODY = {"error": {"code": "not_found", "message": "找不到此題材"}}


class MapCompany(BaseModel):
    ticker: str
    name: str
    role: str | None
    relevance: str | None
    close: float | None
    change_pct: float | None
    badges: list[str]


class MapCategory(BaseModel):
    name: str
    desc: str | None
    placeholder: bool
    companies: list[MapCompany]


class MapLevel(BaseModel):
    level: str
    categories: list[MapCategory]


class TopicMap(BaseModel):
    slug: str
    title: str
    levels: list[MapLevel]


def _members_by_category(
    session: Session, slug: str
) -> dict[tuple[str, str], list]:
    """該題材成員基礎資料，按 (chain_level, category) 二元組分組。

    join companies 取 name/has_futures。key 用 (chain_level, category) 而非只用
    category：分類名稱可能跨 level 重複，二元組確保不互相污染。分類內依 ticker
    排序（topic_companies 無明確排序欄）使輸出穩定。
    """
    stmt = (
        select(
            TopicCompany.chain_level,
            TopicCompany.category,
            TopicCompany.ticker,
            TopicCompany.role,
            TopicCompany.relevance,
            Company.name,
            Company.has_futures,
        )
        .join(Company, Company.ticker == TopicCompany.ticker)
        .where(TopicCompany.topic_slug == slug)
        .order_by(TopicCompany.ticker)
    )
    grouped: dict[tuple[str, str], list] = defaultdict(list)
    for row in session.execute(stmt).all():
        grouped[(row.chain_level, row.category)].append(row)
    return grouped


def _company_card(member, quotes: dict, flows: dict) -> MapCompany:
    quote_rows = quotes.get(member.ticker)
    latest_quote = quote_rows[0] if quote_rows else None
    flow_rows = flows.get(member.ticker)
    latest_flow = flow_rows[0] if flow_rows else None

    close = latest_quote.close if latest_quote else None
    raw_change = latest_quote.change_pct if latest_quote else None
    # 伺服端統一 round 2，UI 不必處理浮點殘差（與 topic detail 一致）。
    change_pct = None if raw_change is None else round(raw_change, 2)

    return MapCompany(
        ticker=member.ticker,
        name=member.name,
        role=member.role,
        relevance=member.relevance,
        close=close,
        change_pct=change_pct,
        badges=badges_for(member.has_futures, latest_flow),
    )


def _build_levels(
    chain_meta: list | None,
    members: dict[tuple[str, str], list],
    quotes: dict,
    flows: dict,
) -> list[MapLevel]:
    """依 chain_meta 骨架逐格展開；placeholder 分類 companies 恆空。"""
    levels: list[MapLevel] = []
    for level in chain_meta or []:
        level_name = level["level"]
        categories: list[MapCategory] = []
        for cat in level.get("categories", []):
            placeholder = bool(cat.get("placeholder", False))
            if placeholder:
                cards: list[MapCompany] = []
            else:
                key = (level_name, cat["name"])
                cards = [
                    _company_card(m, quotes, flows) for m in members.get(key, [])
                ]
            categories.append(
                MapCategory(
                    name=cat["name"],
                    desc=cat.get("desc"),
                    placeholder=placeholder,
                    companies=cards,
                )
            )
        levels.append(MapLevel(level=level_name, categories=categories))
    return levels


@router.get(
    "/topics/{slug}/map",
    response_model=TopicMap,
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
def get_topic_map(slug: str, request: Request):
    engine = request.app.state.engine
    with Session(engine) as session:
        topic = session.get(Topic, slug)
        if topic is None:
            # 統一錯誤格式（與 topic detail、全域 500 handler 一致）；直接回
            # JSONResponse，不經 response_model 序列化。
            return JSONResponse(status_code=404, content=_NOT_FOUND_BODY)

        members = _members_by_category(session, slug)
        # 去重 tickers（同 ticker 跨分類）供批次查最新 quotes/flows。
        tickers = list({m.ticker for rows in members.values() for m in rows})
        quotes = quotes_by_ticker(session, tickers)
        flows = flows_by_ticker(session, tickers)

        return TopicMap(
            slug=topic.slug,
            title=topic.title,
            levels=_build_levels(topic.chain_meta, members, quotes, flows),
        )
