"""全站搜尋 API：GET /api/search.

單一端點 ``GET /api/search?q=...`` 供前端命令面板（Command Palette）跨公司與題材
快速檢索：

- 公司：ticker 前綴（``like "q%"``）OR name 包含（``contains``）。
- 題材：title 包含 OR slug 前綴。
- 各取 limit 10、依 ticker/slug 升冪；固定兩次查詢（各實體一次），無 N+1。

查詢字串 ``q`` 為必填 Query 參數：於參數驗證階段 strip 後為空 → 422、長度 >50 →
422（皆由 FastAPI 轉標準 422，不進入函式主體）。比對一律以 strip 後的字串進行。
"""

from typing import Annotated

from fastapi import APIRouter, Query, Request
from pydantic import AfterValidator, BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Company, Topic

router = APIRouter(tags=["search"])

# 公司／題材各自的回傳上限。
SEARCH_LIMIT = 10
# 查詢字串長度上限（含空白，於 strip 前套用）；避免超長輸入打到 DB。
MAX_QUERY_LEN = 50


def _clean_query(value: str) -> str:
    """strip 後為空即拒絕——空查詢無檢索意義，於驗證階段轉 422。"""
    stripped = value.strip()
    if not stripped:
        raise ValueError("查詢字串不可為空")
    return stripped


# q：必填（無預設）、長度 >50 →422（max_length），strip 後空 →422（AfterValidator）。
# AfterValidator 於長度約束之後執行，回傳的已 strip 值即函式收到的 q。
QueryParam = Annotated[
    str,
    Query(max_length=MAX_QUERY_LEN, description="ticker/slug 前綴或 name/title 包含"),
    AfterValidator(_clean_query),
]


class SearchCompany(BaseModel):
    ticker: str
    name: str
    market: str


class SearchTopic(BaseModel):
    slug: str
    title: str


class SearchResponse(BaseModel):
    companies: list[SearchCompany]
    topics: list[SearchTopic]


@router.get("/search", response_model=SearchResponse)
def search(request: Request, q: QueryParam) -> SearchResponse:
    engine = request.app.state.engine
    with Session(engine) as session:
        companies = (
            session.execute(
                select(Company)
                .where(Company.ticker.like(f"{q}%") | Company.name.contains(q))
                .order_by(Company.ticker)
                .limit(SEARCH_LIMIT)
            )
            .scalars()
            .all()
        )
        topics = (
            session.execute(
                select(Topic)
                .where(Topic.title.contains(q) | Topic.slug.like(f"{q}%"))
                .order_by(Topic.slug)
                .limit(SEARCH_LIMIT)
            )
            .scalars()
            .all()
        )

        return SearchResponse(
            companies=[
                SearchCompany(ticker=c.ticker, name=c.name, market=c.market)
                for c in companies
            ],
            topics=[SearchTopic(slug=t.slug, title=t.title) for t in topics],
        )
