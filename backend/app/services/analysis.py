"""AI 五面向分析 service：脈絡建構 → prompt 產生 → LLM 執行 → 結果落庫。

四個純函式（``build_context`` / ``build_prompt`` / ``parse_llm_response``）與一個
背景執行入口（``run_analysis``）。分工：

- ``build_context``：以固定筆數查詢組出一檔標的的結構化脈絡；各段缺資料則該鍵為
  ``None`` 或空 list，絕不炸。重用 ``app.api.queries`` 的批次／最新查詢與時間下界
  （法人段例外——需近 20 個交易日，自帶 40 日曆日下界直查，見 ``_recent_flows``），
  與其他 API 同口徑、避免歷史累積後的無界掃描。
- ``build_prompt``：把脈絡段落化成 system／user 兩段提示。system 明訂輸出契約
  （JSON only、五面向鍵名精確、scores 0-100 整數、reasons 2-3 句 list、summary 一句、
  不要 markdown fence）；user 只列「有資料」的段落，並依 mode 附上分析重點指示。
- ``parse_llm_response``：容忍 ```json fence，json.loads 後嚴格驗證五面向契約；任一
  不符即 raise ``LLMError``（訊息含原因、不含回應全文）。
- ``run_analysis``：背景任務入口。獨立 Session，僅處理 pending 列（防重入）→
  status=running → 呼叫 provider
  （``LLMError`` 或 parse 失敗均計為一次失敗，重試 1 次、間隔 1 秒）→ 成功寫結果、
  兩次失敗寫 failed。**全程 try/except 兜底，絕不 raise**（背景任務不能炸行程）。

五面向鍵名與 ``total`` 的計分順序皆以 ``app.llm.ASPECTS`` 為單一來源。
"""

from __future__ import annotations

import json
import logging
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.queries import (
    FUNDAMENTALS_LOOKBACK_MONTHS,
    QUOTES_LOOKBACK_DAYS,
    cutoff_date,
    cutoff_month,
    latest_rows,
    quotes_by_ticker,
)
from app.core.config import settings
from app.db.models import (
    AiAnalysis,
    Company,
    Fundamental,
    InstitutionalFlow,
    MajorHolder,
    MopsAnnouncement,
    PerDaily,
    Topic,
    TopicCompany,
)
from app.llm import ASPECTS, LLMError, get_provider, provider_label

logger = logging.getLogger(__name__)

# 三種分析模式（前端下拉即此三值；status 存 running/done/failed 見 AiAnalysis 註解）。
MODES: tuple[str, ...] = ("近期觀察", "中期展望", "全面檢視")

# 法人淨額合計取樣筆數（近 20 個交易日）。不重用 queries.flows_by_ticker——其
# 21 日曆日窗僅涵蓋約 5 個交易日，取不滿 20 筆；改以 40 日曆日下界（≈ 20+ 個
# 交易日含假期餘裕）直查，依 date 降冪取前 FLOWS_SAMPLE 筆。
FLOWS_SAMPLE = 20
FLOWS_CONTEXT_LOOKBACK_DAYS = 40
# 近 5 日收盤序列長度。
RECENT_CLOSES = 5
# 近期重大訊息取樣筆數。
ANNOUNCEMENTS_LIMIT = 5
# 兩次失敗間的重試間隔（秒）。
RETRY_DELAY_SECONDS = 1
# 總嘗試次數（1 次原始 + 1 次重試）。
MAX_ATTEMPTS = 2


# ── build_context ───────────────────────────────────────────────────────────
def _summarize_quotes(rows: list) -> dict | None:
    """近 60 日 quotes 摘要：筆數、最新收盤/漲跌、區間高低、近 5 日收盤序列（時序舊→新）。"""
    if not rows:
        return None
    closes = [r.close for r in rows if r.close is not None]
    latest = rows[0]
    # rows 依 date 降冪；近 5 筆反轉為時序（舊→新）並過濾缺值（與 closes 一致）。
    recent = [
        r.close for r in reversed(rows[:RECENT_CLOSES]) if r.close is not None
    ]
    return {
        "count": len(rows),
        "latest_close": latest.close,
        "latest_change_pct": latest.change_pct,
        "high": max(closes) if closes else None,
        "low": min(closes) if closes else None,
        "recent_closes": recent,
    }


def _recent_flows(session: Session, ticker: str) -> list[InstitutionalFlow]:
    """近 20 個交易日法人買賣超：40 日曆日下界、date 降冪取前 FLOWS_SAMPLE 筆。"""
    return (
        session.execute(
            select(InstitutionalFlow)
            .where(
                InstitutionalFlow.ticker == ticker,
                InstitutionalFlow.date >= cutoff_date(FLOWS_CONTEXT_LOOKBACK_DAYS),
            )
            .order_by(InstitutionalFlow.date.desc())
            .limit(FLOWS_SAMPLE)
        )
        .scalars()
        .all()
    )


def _summarize_flows(rows: list) -> dict | None:
    """法人近 N 筆淨額合計（外資/投信/自營，缺值以 0 計）。"""
    if not rows:
        return None
    return {
        "count": len(rows),
        "foreign_net_sum": sum(f.foreign_net or 0 for f in rows),
        "trust_net_sum": sum(f.trust_net or 0 for f in rows),
        "dealer_net_sum": sum(f.dealer_net or 0 for f in rows),
    }


def _major_holder(session: Session, ticker: str) -> dict | None:
    """大戶比最新值＋前一週差（major_holders 最新兩筆，不足兩筆則差為 None）。"""
    rows = (
        session.execute(
            select(MajorHolder)
            .where(MajorHolder.ticker == ticker)
            .order_by(MajorHolder.week.desc())
            .limit(2)
        )
        .scalars()
        .all()
    )
    if not rows:
        return None
    latest = rows[0]
    diff = None
    if len(rows) == 2:
        diff = round(latest.ratio_400up - rows[1].ratio_400up, 2)
    return {
        "week": latest.week,
        "ratio_400up": latest.ratio_400up,
        "prev_week_diff": diff,
    }


def _fundamental(session: Session, ticker: str) -> dict | None:
    """最新月營收＋YoY（latest_rows，月頻下界）。"""
    row = latest_rows(
        session,
        Fundamental,
        Fundamental.month,
        [ticker],
        cutoff_month(FUNDAMENTALS_LOOKBACK_MONTHS),
    ).get(ticker)
    if row is None:
        return None
    return {"month": row.month, "revenue": row.revenue, "yoy": row.yoy}


def _valuation(session: Session, ticker: str) -> dict | None:
    """最新 PER/PBR/殖利率（latest_rows，日頻下界）。"""
    row = latest_rows(
        session, PerDaily, PerDaily.date, [ticker], cutoff_date(QUOTES_LOOKBACK_DAYS)
    ).get(ticker)
    if row is None:
        return None
    return {"per": row.per, "pbr": row.pbr, "dividend_yield": row.dividend_yield}


def _topics(session: Session, ticker: str) -> list[dict]:
    """所屬題材（topic title＋該 ticker 在題材內的 role 清單，distinct）。"""
    rows = session.execute(
        select(Topic.title, TopicCompany.role)
        .join(TopicCompany, TopicCompany.topic_slug == Topic.slug)
        .where(TopicCompany.ticker == ticker)
        .order_by(Topic.slug)
    ).all()
    grouped: dict[str, list[str]] = {}
    for title, role in rows:
        roles = grouped.setdefault(title, [])
        if role and role not in roles:
            roles.append(role)
    return [{"title": title, "roles": roles} for title, roles in grouped.items()]


def _announcements(session: Session, ticker: str) -> list[str]:
    """近 5 筆公告標題（mops_announcements 該 ticker，published_at 降冪）。"""
    rows = session.execute(
        select(MopsAnnouncement.title)
        .where(MopsAnnouncement.ticker == ticker)
        .order_by(MopsAnnouncement.published_at.desc())
        .limit(ANNOUNCEMENTS_LIMIT)
    ).all()
    return [title for (title,) in rows]


def build_context(session: Session, ticker: str) -> dict:
    """組出一檔標的的結構化分析脈絡（固定查詢數；各段缺資料 → None／空 list）。"""
    company = session.get(Company, ticker)
    quotes = quotes_by_ticker(session, [ticker]).get(ticker, [])
    flows = _recent_flows(session, ticker)
    return {
        "ticker": ticker,
        "name": company.name if company else None,
        "quote": _summarize_quotes(quotes),
        "flows": _summarize_flows(flows),
        "major_holder": _major_holder(session, ticker),
        "fundamental": _fundamental(session, ticker),
        "valuation": _valuation(session, ticker),
        "topics": _topics(session, ticker),
        "announcements": _announcements(session, ticker),
    }


# ── build_prompt ────────────────────────────────────────────────────────────
_ASPECT_KEYS = "、".join(ASPECTS)

_SYSTEM_PROMPT = (
    "你是一位專業的台股證券分析師，擅長從題材、基本面、技術面、籌碼面與新聞面"
    "五個面向綜合評估個股。請全程以繁體中文分析。\n\n"
    "你必須「只」輸出一個 JSON 物件，不得包含任何額外文字、前後說明，也"
    "「不要」使用 markdown 程式碼圍欄（不要 ```json 或 ``` 包裹）。\n"
    "JSON 結構如下：\n"
    f"- scores：物件，恰好五個鍵「{_ASPECT_KEYS}」，每個值為 0 至 100 的整數。\n"
    f"- reasons：物件，恰好五個鍵「{_ASPECT_KEYS}」，每個值為 2 至 3 句繁體中文"
    "理由組成的字串陣列（array of string）。\n"
    "- summary：字串，一句話的綜合結論。\n"
    "五個鍵名必須與上列完全一致，不得翻譯、增刪或改寫。"
)

# 依 mode 的分析重點指示——三者互異，影響模型的面向權重。
_MODE_INSTRUCTIONS = {
    "近期觀察": (
        "本次為「近期觀察」模式：請側重技術面與籌碼面的短線訊號，"
        "評分時提高技術面與籌碼面的權重。"
    ),
    "中期展望": (
        "本次為「中期展望」模式：請側重基本面與題材面的中期驅動力，"
        "評分時提高基本面與題材面的權重。"
    ),
    "全面檢視": (
        "本次為「全面檢視」模式：請對題材、基本、技術、籌碼、新聞五個面向"
        "給予均衡權重，全面評估。"
    ),
}


def _context_sections(ctx: dict) -> list[str]:
    """把有資料的脈絡段落化（無資料的段不列）。"""
    lines: list[str] = []
    q = ctx["quote"]
    if q:
        lines.append(
            f"【近期行情】近 {q['count']} 個交易日；最新收盤 {q['latest_close']}，"
            f"最新漲跌幅 {q['latest_change_pct']}%；區間高 {q['high']} / 低 {q['low']}；"
            f"近 5 日收盤序列（舊→新）{q['recent_closes']}。"
        )
    f = ctx["flows"]
    if f:
        lines.append(
            f"【法人籌碼】近 {f['count']} 個交易日三大法人淨額合計："
            f"外資 {f['foreign_net_sum']}、投信 {f['trust_net_sum']}、"
            f"自營商 {f['dealer_net_sum']}（單位：股，正為買超）。"
        )
    h = ctx["major_holder"]
    if h:
        if h["prev_week_diff"] is None:
            diff = "（無前一週資料可比）"
        else:
            diff = f"，較前一週變動 {h['prev_week_diff']:+} 個百分點"
        lines.append(
            f"【大戶持股】{h['week']} 400 張以上大戶持股比 {h['ratio_400up']}%{diff}。"
        )
    fund = ctx["fundamental"]
    if fund:
        lines.append(
            f"【基本面】最新月營收月份 {fund['month']}，營收 {fund['revenue']}（千元），"
            f"年增率（YoY）{fund['yoy']}%。"
        )
    val = ctx["valuation"]
    if val:
        lines.append(
            f"【評價】本益比 PER {val['per']}、股價淨值比 PBR {val['pbr']}、"
            f"殖利率 {val['dividend_yield']}%。"
        )
    topics = ctx["topics"]
    if topics:
        parts = []
        for t in topics:
            roles = "／".join(t["roles"]) if t["roles"] else "未標註"
            parts.append(f"{t['title']}（角色：{roles}）")
        lines.append("【所屬題材】" + "；".join(parts) + "。")
    anns = ctx["announcements"]
    if anns:
        lines.append("【近期重大訊息】" + "；".join(anns) + "。")
    return lines


def build_prompt(context: dict, mode: str) -> tuple[str, str]:
    """回傳 (system, user)；未知 mode → ValueError。"""
    if mode not in MODES:
        raise ValueError(f"未知的分析模式：{mode!r}")
    name = context.get("name") or "（名稱未知）"
    header = f"請分析以下台股標的：{name}（代號 {context['ticker']}）。"
    sections = _context_sections(context)
    body = "\n".join(sections) if sections else "（目前缺乏可用的量化資料，請就一般認知審慎評估。）"
    user = f"{header}\n\n{body}\n\n{_MODE_INSTRUCTIONS[mode]}"
    return _SYSTEM_PROMPT, user


# ── parse_llm_response ──────────────────────────────────────────────────────
def _strip_fence(text: str) -> str:
    """移除可能的 ```json / ``` markdown 圍欄。"""
    s = text.strip()
    if not s.startswith("```"):
        return s
    lines = s.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def parse_llm_response(text: str) -> dict:
    """strip fence → json.loads → 嚴格驗證五面向契約；任一不符 raise LLMError。"""
    if not isinstance(text, str):
        raise LLMError("AI 回應格式非文字，無法解析。")
    try:
        data = json.loads(_strip_fence(text))
    except json.JSONDecodeError as exc:
        raise LLMError(f"AI 回應不是有效的 JSON：{exc.msg}") from exc
    if not isinstance(data, dict):
        raise LLMError("AI 回應的頂層不是 JSON 物件。")

    expected = set(ASPECTS)
    scores = data.get("scores")
    reasons = data.get("reasons")
    summary = data.get("summary")

    if not isinstance(scores, dict) or set(scores) != expected:
        raise LLMError("AI 回應的 scores 未包含完整的五面向鍵。")
    if not isinstance(reasons, dict) or set(reasons) != expected:
        raise LLMError("AI 回應的 reasons 未包含完整的五面向鍵。")
    for aspect, score in scores.items():
        # bool 為 int 子類，明確排除；分數須為 0-100 的整數。
        if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 100:
            raise LLMError(f"AI 回應的分數不合法（{aspect} 須為 0-100 的整數）。")
    for aspect, items in reasons.items():
        if (
            not isinstance(items, list)
            or not items
            or not all(isinstance(s, str) and s.strip() for s in items)
        ):
            raise LLMError(f"AI 回應的理由不合法（{aspect} 須為非空的字串陣列）。")
    if not isinstance(summary, str) or not summary.strip():
        raise LLMError("AI 回應缺少有效的 summary（須為非空字串）。")

    return {"scores": scores, "reasons": reasons, "summary": summary}


# ── run_analysis（背景任務）──────────────────────────────────────────────────
def _complete_once(provider, system: str, user: str) -> dict:
    """呼叫 provider 並解析——complete 或 parse 失敗均 raise LLMError。"""
    return parse_llm_response(provider.complete(system, user))


def _complete_with_retry(provider, system: str, user: str) -> dict:
    """LLMError（含 parse 失敗）重試 1 次、間隔 1 秒；兩次皆失敗則 raise 最後一次。"""
    last_err: LLMError | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            return _complete_once(provider, system, user)
        except LLMError as exc:
            last_err = exc
            logger.warning("AI 分析第 %d 次嘗試失敗：%s", attempt + 1, exc)
            if attempt < MAX_ATTEMPTS - 1:
                time.sleep(RETRY_DELAY_SECONDS)
    assert last_err is not None  # 迴圈至少執行一次
    raise last_err


def _friendly_error(exc: Exception) -> str:
    """對使用者友善、不洩漏內部細節的錯誤訊息。"""
    if isinstance(exc, LLMError):
        return f"AI 分析失敗：{exc}"
    return "AI 分析發生未預期的錯誤，請稍後再試。"


def run_analysis(engine, analysis_id: int) -> None:
    """背景執行一筆分析：讀列（須為 pending）→ running → 呼叫 LLM（重試 1 次）→ done/failed。

    只處理 ``status == "pending"`` 的列——非 pending 表示已被處理（或處理中），
    log warning 後直接 return，防止背景任務重複執行同一列。

    **絕不 raise**：所有例外都在內部處理並落庫為 failed，避免炸掉背景任務行程。
    """
    try:
        with Session(engine) as session:
            row = session.get(AiAnalysis, analysis_id)
            if row is None:
                logger.error("run_analysis：找不到 analysis id=%s，略過。", analysis_id)
                return
            if row.status != "pending":
                logger.warning(
                    "run_analysis：analysis id=%s 狀態為 %s（非 pending），略過重複執行。",
                    analysis_id,
                    row.status,
                )
                return

            row.status = "running"
            session.commit()

            try:
                context = build_context(session, row.ticker)
                system, user = build_prompt(context, row.mode)
                provider = get_provider(settings)
                result = _complete_with_retry(provider, system, user)
            except Exception as exc:  # noqa: BLE001 — 背景任務兜底
                logger.warning(
                    "AI 分析 id=%s 最終失敗：%s", analysis_id, exc, exc_info=True
                )
                row.status = "failed"
                row.error = _friendly_error(exc)
                session.commit()
                return

            scores = result["scores"]
            row.scores = scores
            row.reasons = result["reasons"]
            row.summary = result["summary"]
            row.total = round(sum(scores.values()) / len(scores), 1)
            row.model = provider_label(settings)
            row.status = "done"
            row.error = None
            session.commit()
    except Exception:  # noqa: BLE001 — 背景任務絕不炸行程
        logger.exception("run_analysis id=%s 發生未預期例外（已吞下）。", analysis_id)
