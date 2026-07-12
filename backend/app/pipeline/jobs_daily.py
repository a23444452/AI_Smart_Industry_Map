"""每日焦點資料管線 jobs — 指數快照、市場統計、重大訊息.

Split out of :mod:`app.pipeline.jobs` (which holds the quotes / institutional
fetches) to keep each file under the ~300-line ceiling: the three 每日焦點 jobs
here feed the daily-focus page (index ticker, 全市場法人金額/信用交易, 重大訊息)
and share nothing with the treemap-oriented quotes jobs beyond the runner
contract.

Every callable obeys the runner contract — it stages DB changes on the session
it is handed and returns; the runner owns commit/rollback. Jobs must NOT call
``session.commit()`` / ``session.rollback()`` themselves (see
``app.pipeline.runner``). The ``_upsert_*`` helpers are also imported by
``jobs_backfill.backfill_market_stats`` so the daily fetch and the historical
walk persist byte-identically.
"""

from __future__ import annotations

from datetime import datetime

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.db.base import utcnow
from app.pipeline.jobs import _TAIPEI, _known_tickers  # 單一定義來源，避免雙重維護
from app.pipeline.sources import (
    mops,
    tpex_per,
    twse_bfi82u,
    twse_margin,
    twse_per,
    yahoo_indices,
)
from app.pipeline.sources._common import SourceFetchError

# 「合計」列不入庫：它是各身份別的衍生總和，前端可自行加總，存了只會與明細重複。
_TOTAL_UNIT = "合計"

# 單日 MOPS 重大訊息入庫上限。正常交易日全市場約數十至一兩百則；破 500 多半是
# 端點回傳異常或欄名漂移導致的爆量，截斷並 log 以免灌爆資料庫。
_MOPS_MAX_ROWS = 500


def _taipei_today_iso() -> str:
    """今日（台北時區）ISO 日期。收盤後執行時當日資料已出。"""
    return datetime.now(_TAIPEI).date().isoformat()


# --------------------------------------------------------------------------- #
# fetch_indices — Yahoo 指數快照 → index_snapshots
# --------------------------------------------------------------------------- #


def fetch_indices(session: Session) -> None:
    """Fetch每檔追蹤指數的現值快照 into ``index_snapshots`` (symbol PK 覆寫).

    Loops :data:`yahoo_indices.SYMBOLS` (7 檔): fetch + parse each, then upsert
    one row per ``symbol`` (overwrite — only the live value is kept, no history),
    stamping ``fetched_at`` with the current naive UTC time.

    Resilience: a single symbol that fails to fetch/parse — or parses to a null
    price (``price`` is NOT NULL, a priceless snapshot is useless) — is logged
    and skipped so one bad symbol can't abort the row. Only when **every** symbol
    fails is a ``RuntimeError`` raised, so the runner records the run as failed.
    A partial success stages the rows that worked and returns normally.

    Contract: stages changes only; the runner commits/rolls back.
    """
    written = 0
    failed = 0
    total = len(yahoo_indices.SYMBOLS)
    for symbol in yahoo_indices.SYMBOLS:
        try:
            row = yahoo_indices.parse(yahoo_indices.fetch(symbol), symbol)
        except Exception as exc:  # noqa: BLE001 - one symbol must not abort the row
            failed += 1
            logger.warning("fetch_indices: 跳過 {} — {}", symbol, exc)
            continue
        if row["price"] is None:
            failed += 1
            logger.warning("fetch_indices: 跳過 {} — 現值缺失（price is None）", symbol)
            continue

        snap = session.get(models.IndexSnapshot, symbol)
        if snap is None:
            snap = models.IndexSnapshot(symbol=symbol)
            session.add(snap)
        snap.name = row["name"]
        snap.price = row["price"]
        snap.change = row["change"]
        snap.change_pct = row["change_pct"]
        snap.fetched_at = utcnow()
        written += 1

    if total and failed == total:
        # 全部 7 檔皆失敗不是個別 symbol 的問題——多半是 Yahoo 端點封鎖/掛掉，
        # 屬系統性失敗，raise 讓 runner 記 failed 並重試。
        raise RuntimeError(
            f"fetch_indices: 全部 {total} 檔指數皆抓取失敗，疑似 Yahoo 端點異常"
        )
    logger.info("fetch_indices: 更新 {} 檔指數快照（跳過 {} 檔）", written, failed)


# --------------------------------------------------------------------------- #
# fetch_market_stats — 全市場法人金額 + 信用交易 → market_flows / margin_balances
# --------------------------------------------------------------------------- #


def _upsert_market_flows(session: Session, rows: list[dict]) -> int:
    """Upsert neutral BFI82U dicts into ``market_flows`` (date+unit PK 覆寫).

    The 「合計」row is skipped — it is a derived total, not a 身份別 (see
    ``_TOTAL_UNIT``). Returns the number of rows written. Shared by
    :func:`fetch_market_stats` and ``backfill_market_stats``.
    """
    written = 0
    for row in rows:
        if row["unit"] == _TOTAL_UNIT:
            continue
        flow = session.get(models.MarketFlow, (row["date"], row["unit"]))
        if flow is None:
            flow = models.MarketFlow(date=row["date"], unit=row["unit"])
            session.add(flow)
        flow.buy = row["buy"]
        flow.sell = row["sell"]
        flow.net = row["net"]
        written += 1
    return written


def _upsert_margin_balances(session: Session, rows: list[dict]) -> int:
    """Upsert neutral MI_MARGN dicts into ``margin_balances`` (date+item PK 覆寫).

    Returns the number of rows written. Shared by :func:`fetch_market_stats` and
    ``backfill_market_stats``.
    """
    written = 0
    for row in rows:
        bal = session.get(models.MarginBalance, (row["date"], row["item"]))
        if bal is None:
            bal = models.MarginBalance(date=row["date"], item=row["item"])
            session.add(bal)
        bal.buy = row["buy"]
        bal.sell = row["sell"]
        bal.prev_balance = row["prev_balance"]
        bal.today_balance = row["today_balance"]
        written += 1
    return written


def fetch_market_stats(session: Session) -> None:
    """Fetch 全市場法人買賣金額 (BFI82U) + 信用交易 (MI_MARGN) for 台北今日.

    The two sources are fetched + upserted under **independent** try/except
    blocks so one failing source neither aborts the other nor discards the
    other's already-staged rows: a single-source failure is logged as a warning
    and the run still succeeds on the source that worked. Only when **both**
    sources raise ``SourceFetchError`` is the first error re-raised so the runner
    records the run as failed. On a holiday both parse to ``[]`` — no writes,
    still a normal (successful) end.

    Writes ``market_flows`` (「合計」skipped, see :func:`_upsert_market_flows`)
    and ``margin_balances`` (item 原名保留).

    Contract: stages changes only; the runner commits/rolls back.
    """
    date = _taipei_today_iso()
    bfi_error: SourceFetchError | None = None
    margin_error: SourceFetchError | None = None
    flow_rows = margin_rows = 0

    try:
        flows = twse_bfi82u.parse(twse_bfi82u.fetch(date), date)
    except SourceFetchError as exc:
        bfi_error = exc
        logger.warning("fetch_market_stats: BFI82U 略過 — {}", exc)
    else:
        flow_rows = _upsert_market_flows(session, flows)

    try:
        margins = twse_margin.parse(twse_margin.fetch(date), date)
    except SourceFetchError as exc:
        margin_error = exc
        logger.warning("fetch_market_stats: MI_MARGN 略過 — {}", exc)
    else:
        margin_rows = _upsert_margin_balances(session, margins)

    if bfi_error is not None and margin_error is not None:
        # 只有兩來源皆 SourceFetchError 才 raise（讓 runner 記 failed）。單一來源
        # 失敗則另一來源已 stage 的資料照常提交；一失敗一假日空亦不 raise。
        raise bfi_error
    logger.info(
        "fetch_market_stats: market_flows {} 列、margin_balances {} 列（{}）",
        flow_rows,
        margin_rows,
        date,
    )


# --------------------------------------------------------------------------- #
# fetch_mops — 重大訊息（上市 + 上櫃）→ mops_announcements
# --------------------------------------------------------------------------- #


def _safe_fetch_mops(fetch_fn, label: str) -> tuple[list[dict], bool]:
    """Call a MOPS fetch; on ``SourceFetchError`` log + return ``([], False)``.

    The bool flags success so :func:`fetch_mops` can tell「單市場失敗」(other
    market still usable) from「兩市場皆失敗」(raise).
    """
    try:
        return fetch_fn(), True
    except SourceFetchError as exc:
        logger.warning("fetch_mops: {} 來源略過 — {}", label, exc)
        return [], False


def fetch_mops(session: Session) -> None:
    """Fetch今日重大訊息 (上市 + 上櫃) merged → insert into ``mops_announcements``.

    No company filter — every filing is kept. Insert-only with an explicit
    existence check on the ``(ticker, title, published_at)`` unique key, so a
    same-day rerun (or an overlap between the two feeds) skips the duplicate
    rather than raising an IntegrityError. Capped at :data:`_MOPS_MAX_ROWS` per
    run (excess truncated + logged).

    Two failure/health signals: when both feeds' raw is non-empty yet parse
    yields nothing, a warning flags suspected 欄名漂移 (the date/time keys
    drifted so every row was skipped). A single-market fetch failure is skipped
    with a warning; only when **both** markets fail to fetch is
    ``SourceFetchError`` raised so the runner records the run as failed.

    Contract: stages changes only; the runner commits/rolls back.
    """
    listed_raw, listed_ok = _safe_fetch_mops(mops.fetch_listed, "上市")
    otc_raw, otc_ok = _safe_fetch_mops(mops.fetch_otc, "上櫃")
    if not listed_ok and not otc_ok:
        raise SourceFetchError("MOPS", "MOPS 兩市場皆無法取得，請稍後再試")

    raw_all = listed_raw + otc_raw
    parsed = mops.parse(raw_all)
    if raw_all and not parsed:
        # raw 有資料但解析全數落空 → 多為 發言日期/發言時間 欄位漂移導致逐列跳過。
        logger.warning(
            "fetch_mops: raw {} 筆但解析後為空，疑似欄名漂移，請人工確認", len(raw_all)
        )

    if len(parsed) > _MOPS_MAX_ROWS:
        logger.warning(
            "fetch_mops: 單日 {} 筆超過上限 {}，僅取前 {} 筆",
            len(parsed),
            _MOPS_MAX_ROWS,
            _MOPS_MAX_ROWS,
        )
        parsed = parsed[:_MOPS_MAX_ROWS]

    inserted = 0
    for row in parsed:
        # 先查存在再 insert：撞 (ticker,title,published_at) unique 的列直接跳過。
        # autoflush 會把本批次已 add 的列先寫入，故同批重複也會被這個查詢擋下。
        exists = session.scalar(
            select(models.MopsAnnouncement.id).where(
                models.MopsAnnouncement.ticker == row["ticker"],
                models.MopsAnnouncement.title == row["title"],
                models.MopsAnnouncement.published_at == row["published_at"],
            )
        )
        if exists is not None:
            continue
        session.add(models.MopsAnnouncement(**row))
        inserted += 1
    logger.info("fetch_mops: 新增 {} 則重大訊息（解析 {} 則）", inserted, len(parsed))


# --------------------------------------------------------------------------- #
# fetch_per — 本益比/淨值比/殖利率（上市 + 上櫃）→ per_daily
# --------------------------------------------------------------------------- #


def _upsert_per_daily(session: Session, rows: list[dict], known: set[str]) -> int:
    """Upsert neutral PER dicts into ``per_daily`` (ticker+date PK 覆寫).

    Drops tickers not in ``known`` (feed is whole-market, we only track 收錄公司).
    Overwrite is safe because the daily ``twse_per``/``tpex_per`` snapshot and the
    ``twse_per_history`` backfill emit the **same** columns (per/pbr/dividend_yield)
    — there is no field one carries that the other nulls out (unlike quotes'
    change_pct)；也因此 ``backfill_per`` 才能安全採 insert-only（毋須擔心覆寫
    遺漏欄位——它走自己的內聯邏輯，並未共用本 helper）。Returns rows written.
    """
    written = 0
    for row in rows:
        ticker = row["ticker"]
        if ticker not in known:
            continue
        date = row["date"]
        rec = session.get(models.PerDaily, (ticker, date))
        if rec is None:
            rec = models.PerDaily(ticker=ticker, date=date)
            session.add(rec)
        rec.per = row["per"]
        rec.pbr = row["pbr"]
        rec.dividend_yield = row["dividend_yield"]
        written += 1
    return written


def fetch_per(session: Session) -> None:
    """Fetch 上市 (BWIBBU_ALL) + 上櫃 (peratio_analysis) 當日全市場 PER snapshot.

    Mirrors :func:`fetch_market_stats`'s two-source isolation: each feed is
    fetched + upserted under an **independent** try/except so one failing source
    neither aborts the other nor discards its already-staged rows — a single
    failure logs a warning and the run still succeeds on the source that worked;
    only when **both** raise ``SourceFetchError`` is the first re-raised so the
    runner records the run as failed.

    Both feeds carry a per-row ``Date``; the Taipei trading day is passed as the
    parse fallback for a row missing/blank Date. Rows are filtered to 收錄公司 and
    upserted into ``per_daily`` (see :func:`_upsert_per_daily`).

    Contract: stages changes only; the runner commits/rolls back.
    """
    date = _taipei_today_iso()
    known = _known_tickers(session)
    listed_error: SourceFetchError | None = None
    otc_error: SourceFetchError | None = None
    listed_rows = otc_rows = 0

    try:
        listed = twse_per.parse(twse_per.fetch(), date)
    except SourceFetchError as exc:
        listed_error = exc
        logger.warning("fetch_per: 上市 BWIBBU 略過 — {}", exc)
    else:
        listed_rows = _upsert_per_daily(session, listed, known)

    try:
        otc = tpex_per.parse(tpex_per.fetch(), date)
    except SourceFetchError as exc:
        otc_error = exc
        logger.warning("fetch_per: 上櫃 peratio 略過 — {}", exc)
    else:
        otc_rows = _upsert_per_daily(session, otc, known)

    if listed_error is not None and otc_error is not None:
        # 兩來源皆 SourceFetchError 才 raise（讓 runner 記 failed）；單一來源失敗則
        # 另一來源已 stage 的資料照常提交（與 fetch_market_stats 同策略）。
        raise listed_error
    logger.info("fetch_per: per_daily 上市 {} 列、上櫃 {} 列（{}）", listed_rows, otc_rows, date)
