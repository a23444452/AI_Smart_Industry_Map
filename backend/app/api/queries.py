"""共用批次查詢 helper：成員 quotes / flows 一次查回、按 ticker 分組降冪。

供 ``topics.py``（題材詳情 treemap／chip_signals）與 ``topic_map.py``（產業鏈
地圖公司卡片）共用。行為契約：

- 一次 ``IN (tickers)`` 查回全部成員資料，Python 分組——資料量小（每題材
  十餘檔 × 數十交易日），毋須 window function 或 per-ticker N+1。
- 每組依 ``date`` 降冪：index 0 是該 ticker 最新一筆、index N 是 N 筆前。
- 查詢帶時間下界（日曆日），避免歷史回填累積後的無界掃描：quotes 60 日
  （覆蓋 month 偏移所需 21 個交易日＋假期餘裕）、flows 21 日（覆蓋 5 個
  交易日餘裕）。
"""

from collections import defaultdict
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.db.models import InstitutionalFlow, QuoteDaily

# 查詢時間下界（日曆日）：避免無界掃描。60 日曆日覆蓋 21 個交易日＋假期餘裕；
# 21 日曆日覆蓋 5 個交易日餘裕。
QUOTES_LOOKBACK_DAYS = 60
FLOWS_LOOKBACK_DAYS = 21


def cutoff_date(lookback_days: int) -> str:
    """今日（UTC）往回 ``lookback_days`` 日曆日的 ISO 日期字串（date 欄為 ISO 字串，可直接字串比較）。"""
    return (utcnow().date() - timedelta(days=lookback_days)).isoformat()


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
