"""AI 分析 API：analyze（建請求）、analyses/{id}（查單筆）、leaderboard（榜單）三端點.

- ``POST /api/ai/analyze`` — body ``{ticker, mode}``（mode 為三值 Literal，非法→422）。
  ticker 不在 companies → 404（統一錯誤格式）。同 ticker+mode 已有 pending/running
  列 → 409（避免同一分析並發重跑）。否則建 ``AiAnalysis(status="pending")`` →
  **先 commit 落地**（背景任務會開新 Session 讀這一列，必須先存在）→ 以
  ``background_tasks`` 排入 ``run_analysis`` → 202 ``{analysis_id}``。

- ``GET /api/ai/analyses/{id}`` — 回單筆完整欄位；name 由 companies join（缺→null）；
  結果欄位（scores/reasons/summary/total/model/error）依 status 誠實 nullable。
  不存在 → 404。

- ``GET /api/ai/leaderboard?sort=&mode=`` — 每 ticker 取最新一筆 ``status=done``
  （mode 有值則限定該 mode）→ 依 total 降冪（strong，預設）/升冪（weak）→ top 50，
  帶 rank。name 由 companies join。

時間戳一律經 ``to_utc_iso`` 帶 ``Z``（與其他 API 同口徑）。
"""

from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.serializers import to_utc_iso
from app.db.base import utcnow
from app.db.models import AiAnalysis, Company
from app.services.analysis import MODES, run_analysis

router = APIRouter(tags=["ai"])

# 三種分析模式（單一來源在 services.analysis.MODES）。Literal 供 Pydantic 於請求
# 驗證階段擋掉非法值（→422），與 MODES 內容保持一致。
AnalysisMode = Literal["近期觀察", "中期展望", "全面檢視"]

# 榜單上限（top N）。
LEADERBOARD_LIMIT = 50

_COMPANY_NOT_FOUND = {"error": {"code": "not_found", "message": "找不到此公司"}}
_ANALYSIS_NOT_FOUND = {"error": {"code": "not_found", "message": "找不到此分析"}}
_CONFLICT_BODY = {
    "error": {"code": "conflict", "message": "該個股同模式分析進行中，請稍候"}
}

# 「進行中」的狀態集合——這些狀態下同 ticker+mode 不得再建新請求。
_ACTIVE_STATUSES = ("pending", "running")

# 孤兒 running 回收窗：只有 created_at 在近 10 分鐘內的 pending/running 列才算「真的
# 進行中」而阻擋新觸發。process crash 會留下永遠停在 running 的孤兒列——若不設下界，
# 這種列將永久 409、使該 ticker+mode 再也無法重新分析。逾時的舊列仍保留在 DB 供查詢
# （GET /analyses/{id} 照樣讀得到），且榜單只取 status=done，不受這些孤兒列影響。
ACTIVE_WINDOW_MINUTES = 10


# 常數一致性守衛：Literal 與 MODES 不同步時提早在載入期炸出，避免驗證行為與常數
# 漂移。用顯式 raise 而非 assert——assert 在 `python -O` 最佳化模式會被剝除。
if set(AnalysisMode.__args__) != set(MODES):  # pragma: no cover - 載入期守衛
    raise RuntimeError("AnalysisMode Literal 與 services.analysis.MODES 不一致")


# ── POST /api/ai/analyze ─────────────────────────────────────────────────────
class AnalyzeRequest(BaseModel):
    ticker: str
    mode: AnalysisMode

    @field_validator("ticker")
    @classmethod
    def _strip_ticker(cls, v: str) -> str:
        # strip 前後空白；全空白（strip 後為空）無意義 → raise，FastAPI 轉 422。
        stripped = v.strip()
        if not stripped:
            raise ValueError("ticker 不可為空")
        return stripped


@router.post("/ai/analyze", status_code=202)
def create_analysis(
    body: AnalyzeRequest, request: Request, background_tasks: BackgroundTasks
):
    engine = request.app.state.engine
    with Session(engine) as session:
        if session.get(Company, body.ticker) is None:
            return JSONResponse(status_code=404, content=_COMPANY_NOT_FOUND)

        # check-then-insert（best-effort）：先查同 ticker+mode 是否已有進行中的列。
        # 單行程（uvicorn 單 worker）下兩請求幾乎不會真正並發到穿透此檢查；即便
        # 罕見競態穿透，run_analysis 亦有 pending 防重入兜底，最多多建一列冗餘 pending。
        active_since = utcnow() - timedelta(minutes=ACTIVE_WINDOW_MINUTES)
        active = session.execute(
            select(AiAnalysis.id)
            .where(
                AiAnalysis.ticker == body.ticker,
                AiAnalysis.mode == body.mode,
                AiAnalysis.status.in_(_ACTIVE_STATUSES),
                # 時間下界：逾時的孤兒 running/pending（多半來自 crash）不再阻擋。
                AiAnalysis.created_at >= active_since,
            )
            .limit(1)
        ).first()
        if active is not None:
            return JSONResponse(status_code=409, content=_CONFLICT_BODY)

        analysis = AiAnalysis(ticker=body.ticker, mode=body.mode, status="pending")
        session.add(analysis)
        # 先 commit 落地：背景任務會開新 Session 依 id 讀這一列，必須先存在於 DB。
        session.commit()
        analysis_id = analysis.id

    # commit 之後才排背景任務——確保 run_analysis 讀得到 pending 列。
    background_tasks.add_task(run_analysis, engine, analysis_id)
    return {"analysis_id": analysis_id}


# ── GET /api/ai/analyses/{id} ────────────────────────────────────────────────
class AnalysisDetail(BaseModel):
    id: int
    ticker: str
    name: str | None
    mode: str
    status: str
    scores: dict | None
    reasons: dict | None
    summary: str | None
    total: float | None
    model: str | None
    error: str | None
    created_at: str | None


@router.get("/ai/analyses/{analysis_id}")
def get_analysis(analysis_id: int, request: Request):
    engine = request.app.state.engine
    with Session(engine) as session:
        row = session.get(AiAnalysis, analysis_id)
        if row is None:
            return JSONResponse(status_code=404, content=_ANALYSIS_NOT_FOUND)
        company = session.get(Company, row.ticker)
        return AnalysisDetail(
            id=row.id,
            ticker=row.ticker,
            name=company.name if company else None,
            mode=row.mode,
            status=row.status,
            scores=row.scores,
            reasons=row.reasons,
            summary=row.summary,
            total=row.total,
            model=row.model,
            error=row.error,
            created_at=to_utc_iso(row.created_at),
        )


# ── GET /api/ai/leaderboard ──────────────────────────────────────────────────
class LeaderboardItem(BaseModel):
    rank: int
    ticker: str
    name: str | None
    mode: str
    scores: dict | None
    total: float | None
    model: str | None
    created_at: str | None


class LeaderboardResponse(BaseModel):
    items: list[LeaderboardItem]


@router.get("/ai/leaderboard", response_model=LeaderboardResponse)
def leaderboard(
    request: Request,
    sort: Literal["strong", "weak"] = Query("strong"),
    mode: AnalysisMode | None = Query(None),
) -> LeaderboardResponse:
    engine = request.app.state.engine
    with Session(engine) as session:
        stmt = select(AiAnalysis).where(AiAnalysis.status == "done")
        if mode is not None:
            stmt = stmt.where(AiAnalysis.mode == mode)
        # 依 created_at 降冪、id 降冪——同 ticker 首次出現者即最新一筆 done。
        stmt = stmt.order_by(AiAnalysis.created_at.desc(), AiAnalysis.id.desc())
        rows = session.execute(stmt).scalars().all()

        latest_by_ticker: dict[str, AiAnalysis] = {}
        for r in rows:
            latest_by_ticker.setdefault(r.ticker, r)
        # done 列恆有 total；仍過濾 None 以誠實兜底——無 total 者無從排名，不入榜。
        picked = [r for r in latest_by_ticker.values() if r.total is not None]

        reverse = sort == "strong"  # strong→降冪，weak→升冪
        picked.sort(key=lambda r: r.total, reverse=reverse)
        top = picked[:LEADERBOARD_LIMIT]

        names = dict(
            session.execute(
                select(Company.ticker, Company.name).where(
                    Company.ticker.in_([r.ticker for r in top])
                )
            ).all()
        )

        items = [
            LeaderboardItem(
                rank=i + 1,
                ticker=r.ticker,
                name=names.get(r.ticker),
                mode=r.mode,
                scores=r.scores,
                total=r.total,
                model=r.model,
                created_at=to_utc_iso(r.created_at),
            )
            for i, r in enumerate(top)
        ]
        return LeaderboardResponse(items=items)
