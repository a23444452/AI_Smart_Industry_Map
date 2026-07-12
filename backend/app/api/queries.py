"""共用查詢 helper：批次 quotes/flows、各表最新一列、徽章與行情更新時間。

供 ``topics.py``（題材詳情）、``topic_map.py``（產業鏈地圖）與 ``companies.py``
（公司清單／詳情）共用。行為契約：

- 批次查詢一次 ``IN (tickers)`` 查回全部成員資料，Python 分組——資料量小
  （每題材十餘檔 × 數十交易日），毋須 window function 或 per-ticker N+1。
- 每組依 ``date`` 降冪：index 0 是該 ticker 最新一筆、index N 是 N 筆前。
- 查詢帶時間下界（日曆日），避免歷史回填累積後的無界掃描：quotes 60 日
  （覆蓋 month 偏移所需 21 個交易日＋假期餘裕）、flows 21 日（覆蓋 5 個
  交易日餘裕）、月頻資料 12 個月（見 ``cutoff_month``）。
- ``badges_for``／``quotes_updated_at`` 為徽章與行情更新時間邏輯的單一來源，
  topic_map 與 companies 共用同一口徑。
"""

from collections import defaultdict
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.serializers import to_utc_iso
from app.db.base import utcnow
from app.db.models import InstitutionalFlow, PipelineRun, QuoteDaily

# 查詢時間下界（日曆日）：避免無界掃描。60 日曆日覆蓋 21 個交易日＋假期餘裕；
# 21 日曆日覆蓋 5 個交易日餘裕。
QUOTES_LOOKBACK_DAYS = 60
FLOWS_LOOKBACK_DAYS = 21
# 月頻資料（fundamentals.month 為 "YYYY-MM"）的下界：12 個月綽綽有餘覆蓋
# 「最新一筆月營收」，同時避免歷年累積後的無界掃描。
FUNDAMENTALS_LOOKBACK_MONTHS = 12

# 徽章文字（固定輸出順序：期貨 → 外資 → 投信）。
BADGE_FUTURES = "有股票期貨"
BADGE_FOREIGN_BUY = "外資買超"
BADGE_TRUST_BUY = "投信買超"

# quotes_updated_at 綁定的行情 job 名稱（見 app.pipeline.scheduler）。
QUOTES_JOB_NAME = "fetch_tw_quotes"


def cutoff_date(lookback_days: int) -> str:
    """今日（UTC）往回 ``lookback_days`` 日曆日的 ISO 日期字串（date 欄為 ISO 字串，可直接字串比較）。"""
    return (utcnow().date() - timedelta(days=lookback_days)).isoformat()


def cutoff_month(lookback_months: int) -> str:
    """今日（UTC）往回 ``lookback_months`` 個月的 ``YYYY-MM`` 字串。

    月欄位（如 ``fundamentals.month``）為 ``YYYY-MM``，不能拿 ``cutoff_date`` 的
    ``YYYY-MM-DD`` 來比（``"2026-05" < "2026-05-01"``，同月會被字典序誤排除），
    故月頻下界須用同格式。
    """
    today = utcnow().date()
    total = today.year * 12 + (today.month - 1) - lookback_months
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def period_change(rows: list, offset: int) -> float | None:
    """(最新 close ÷ offset 個交易日前 close − 1)×100，round 2；資料不足或缺值 → None。

    ``rows`` 為單一 ticker 的 quotes，依日期降冪（index 0 最新、index N 為 N 個
    交易日前，見 ``quotes_by_ticker``）。供 topic detail treemap 與 daily movers
    共用週／月報酬計算。
    """
    if len(rows) <= offset:
        return None
    latest_close = rows[0].close
    base_close = rows[offset].close
    if latest_close is None or base_close is None or base_close == 0:
        return None
    return round((latest_close / base_close - 1) * 100, 2)


def quotes_by_ticker(session: Session, tickers: list[str]) -> dict[str, list]:
    """成員近 60 日曆日 quotes 一次查回，按 ticker 分組、日期由新到舊排列。

    每組為降冪，故 index 0 是最新日、index N 是 N 個交易日前。
    """
    if not tickers:
        return {}
    stmt = (
        select(
            QuoteDaily.ticker,
            QuoteDaily.date,
            QuoteDaily.close,
            QuoteDaily.change_pct,
        )
        .where(
            QuoteDaily.ticker.in_(tickers),
            QuoteDaily.date >= cutoff_date(QUOTES_LOOKBACK_DAYS),
        )
        .order_by(QuoteDaily.ticker, QuoteDaily.date.desc())
    )
    grouped: dict[str, list] = defaultdict(list)
    for row in session.execute(stmt).all():
        grouped[row.ticker].append(row)
    return grouped


def flows_by_ticker(
    session: Session, tickers: list[str]
) -> dict[str, list[InstitutionalFlow]]:
    """成員近 21 日曆日法人買賣超，按 ticker 分組、日期由新到舊排列（覆蓋 5 個交易日餘裕）。"""
    if not tickers:
        return {}
    stmt = (
        select(InstitutionalFlow)
        .where(
            InstitutionalFlow.ticker.in_(tickers),
            InstitutionalFlow.date >= cutoff_date(FLOWS_LOOKBACK_DAYS),
        )
        .order_by(InstitutionalFlow.ticker, InstitutionalFlow.date.desc())
    )
    grouped: dict[str, list[InstitutionalFlow]] = defaultdict(list)
    for flow in session.execute(stmt).scalars().all():
        grouped[flow.ticker].append(flow)
    return grouped


def latest_rows(
    session: Session, model, date_col, tickers: list[str], cutoff: str
) -> dict:
    """各 ticker 於 ``cutoff`` 之後最新一列（依 ``date_col`` 取 MAX）；dict[ticker → ORM 物件]。

    date 欄位均為 ISO 字串（``YYYY-MM-DD`` 或 ``YYYY-MM``），MAX 即字典序最新。
    以 (ticker, max_date) 自我 join；date 為複合 PK 一部分，故每 ticker 至多一列。
    ``cutoff`` 為與 ``date_col`` 同格式的下界字串（日頻用 ``cutoff_date``、月頻用
    ``cutoff_month``），比照本模組其他查詢避免歷史累積後的無界掃描——下界外的
    ticker 視同無資料（回 None），呼叫端輸出 nullable。
    """
    if not tickers:
        return {}
    latest = (
        select(model.ticker.label("t"), func.max(date_col).label("d"))
        .where(model.ticker.in_(tickers), date_col >= cutoff)
        .group_by(model.ticker)
        .subquery()
    )
    stmt = select(model).join(
        latest, (model.ticker == latest.c.t) & (date_col == latest.c.d)
    )
    return {row.ticker: row for row in session.execute(stmt).scalars().all()}


def badges_for(has_futures: bool, latest_flow) -> list[str]:
    """依徽章口徑組出徽章清單（順序：期貨 → 外資 → 投信）——單一來源。

    口徑（與題材總覽 ``chip_signals`` 的「近 5 日加總」不同，見 topic_map 模組
    docstring）：``latest_flow`` 為該 ticker 依 date 降冪的**第一筆**法人買賣超
    （無 flows 時為 None），其 ``foreign_net``／``trust_net`` > 0 即掛徽章。
    """
    badges: list[str] = []
    if has_futures:
        badges.append(BADGE_FUTURES)
    if latest_flow is not None:
        if (latest_flow.foreign_net or 0) > 0:
            badges.append(BADGE_FOREIGN_BUY)
        if (latest_flow.trust_net or 0) > 0:
            badges.append(BADGE_TRUST_BUY)
    return badges


def quotes_updated_at(session: Session) -> str | None:
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
