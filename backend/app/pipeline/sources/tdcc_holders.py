"""集保戶股權分散表 (TDCC 集保) source client — CSV streaming.

Endpoint (``getOD.ashx?id=1-5``): a single streamed CSV snapshot of the latest
weekly 集保 (central-securities-depository) shareholding distribution — one row
per ``(證券代號, 持股分級)``, tens of thousands of rows / a few MB. Served as
``text/csv; charset=UTF-8`` **with a UTF-8 BOM**, so :func:`fetch` decodes with
``utf-8-sig`` to strip it.

Real header (recorded 2026-07-03, id=1-5):

    資料日期,證券代號,持股分級,人數,股數,占集保庫存數比例%

    資料日期        : YYYYMMDD (AD, the week's data date / last trading day)
    證券代號        : **space-padded to 6 chars** ('2330  ', '0050  ') —
                      :func:`parse` strips it before matching ``wanted``
    持股分級        : 1–17 (see below); the row's holding-size bucket
    人數            : holder count in that 級距
    股數            : shares held in that 級距
    占集保庫存數比例% : that 級距's share of the security's 集保 holdings

持股分級 (級距) boundaries — 1 張 = 1,000 股 (17 levels observed in id=1-5):

     1: 1–999 股              9: 50,001–100,000
     2: 1,000–5,000          10: 100,001–200,000
     3: 5,001–10,000         11: 200,001–400,000   (≤ 400 張)
     4: 10,001–15,000        12: 400,001–600,000   ┐
     5: 15,001–20,000        13: 600,001–800,000   │  > 400 張
     6: 20,001–30,000        14: 800,001–1,000,000 │  → ratio_400up
     7: 30,001–40,000        15: 1,000,001 以上      ┘
     8: 40,001–50,000        16: 差異數調整 (adjustment)   17: 合計 (total)

Levels 1–15 are the real distribution 級距; level 16 (差異數調整) is a
reconciliation row and level 17 (合計) is the per-security total — both are
excluded from the aggregates so ``holder_count`` is not double-counted.

``ratio_400up`` = Σ 占集保庫存數比例% over 級距 12–15 (holdings > 400 張 /
400,001 股以上) — the "large-holder" concentration proxy the topic charts show.
Because the feed rounds each 級距's % to 2 dp, the 15 級距 sum to ~100 (±0.5),
not exactly 100.

Neutral row shape (Task 5 upserts on ticker+week → ``major_holders``):

    ticker       : 證券代號 (stripped)
    week         : 資料日期 ISO "YYYY-MM-DD"
    ratio_400up  : Σ 占集保庫存數比例% over 級距 12–15, float
    holder_count : Σ 人數 over 級距 1–15 (excl. 差異數調整 & 合計), int | None
"""

from __future__ import annotations

import csv
import io

import httpx

from app.pipeline.sources import _common
from app.pipeline.sources._common import SourceFetchError

STREAM_URL = "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5"

SOURCE = "集保股權分散"

# TDCC serves a plain CSV to a browser UA; a bare/library UA can draw a block.
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

# Columns parse() depends on; a header missing any of these is structural drift.
_REQUIRED_COLUMNS = ("資料日期", "證券代號", "持股分級", "人數", "占集保庫存數比例%")

# 真實級距 1–15 (holder_count numerator); 16 差異數調整 / 17 合計 are excluded.
_HOLDER_LEVELS = frozenset(str(i) for i in range(1, 16))
# > 400 張 (400,001 股以上) buckets that make up ratio_400up.
_RATIO_400UP_LEVELS = frozenset(("12", "13", "14", "15"))


def fetch() -> str:
    """Stream the full TDCC 集保 CSV and return it decoded (BOM stripped).

    Uses ``client.stream`` and aggregates ``iter_bytes`` so httpx never holds a
    second full-body copy the way ``resp.text`` would; the decoded string is
    then materialised whole. At this size (single-digit MB) a full in-memory
    string is acceptable — memory peaks at roughly the raw bytes plus the
    decoded str, not a multiple of it. Raises SourceFetchError (friendly
    message + status code when available) on connection/timeout failure or any
    non-200, so the job layer only ever catches SourceFetchError.
    """
    chunks = bytearray()
    try:
        with httpx.Client(
            timeout=_common.TIMEOUT_SECONDS,
            follow_redirects=True,
            verify=_common._ssl_context(),
        ) as client:
            with client.stream(
                "GET", STREAM_URL, headers={"User-Agent": _BROWSER_UA}
            ) as resp:
                if resp.status_code != 200:
                    raise SourceFetchError(
                        SOURCE,
                        f"{SOURCE} 資料來源回應異常（HTTP {resp.status_code}），請稍後再試",
                        status_code=resp.status_code,
                    )
                for chunk in resp.iter_bytes():
                    chunks.extend(chunk)
    except httpx.HTTPError as exc:
        raise SourceFetchError(
            SOURCE, f"{SOURCE} 資料來源連線失敗，請稍後再試"
        ) from exc

    # decode 也可能失敗（來源改編碼或截斷成非法 UTF-8）——包成 SourceFetchError
    # 讓 job 層只需捕捉單一例外型別，不會漏接 UnicodeDecodeError。
    try:
        return chunks.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SourceFetchError(
            SOURCE, f"{SOURCE} 資料來源內容編碼異常，請稍後再試"
        ) from exc


def parse(csv_text: str, wanted: set[str]) -> list[dict]:
    """Aggregate the 集保 CSV into one neutral row per wanted ``(ticker, week)``.

    Streams the CSV line by line (``csv.reader`` over a StringIO — no full row
    list held) and folds each ticker's 17 級距 rows into a single dict:
    ``ratio_400up`` sums 級距 12–15's 占集保庫存數比例%; ``holder_count`` sums
    級距 1–15's 人數 (skipping 16 差異數調整 and 17 合計). Only tickers in
    ``wanted`` are emitted (證券代號 is space-padded, so it is stripped before
    the membership test); output order follows first appearance.

    ``week`` is the 資料日期 as ISO "YYYY-MM-DD". ``holder_count`` is None when
    no 級距 row carried a parseable 人數 for that ticker. A header missing any
    required column (or empty input) raises SourceFetchError — a layout change
    needs human attention, not a silent empty parse.
    """
    reader = csv.reader(io.StringIO(csv_text.lstrip("﻿")))
    try:
        header = next(reader)
    except StopIteration as exc:
        raise SourceFetchError(
            SOURCE, f"{SOURCE} 資料來源回傳內容無法解析，請稍後再試"
        ) from exc

    col = {name.strip(): i for i, name in enumerate(header)}
    if any(c not in col for c in _REQUIRED_COLUMNS):
        raise SourceFetchError(
            SOURCE, f"{SOURCE} 資料來源欄位結構變動，請人工確認"
        )

    i_date = col["資料日期"]
    i_ticker = col["證券代號"]
    i_level = col["持股分級"]
    i_people = col["人數"]
    i_ratio = col["占集保庫存數比例%"]
    max_i = max(i_date, i_ticker, i_level, i_people, i_ratio)

    agg: dict[tuple[str, str], dict] = {}
    order: list[tuple[str, str]] = []
    saw_wanted = False  # 見過至少一列想要的 ticker（用來區分「空 wanted」與「日期全壞」）
    saw_valid_week = False  # 想要的列中至少一列日期可解析
    for parts in reader:
        if len(parts) <= max_i:
            continue  # truncated/blank line — skip defensively
        ticker = parts[i_ticker].strip()
        if ticker not in wanted:
            continue
        saw_wanted = True
        week = _common.yyyymmdd_to_iso(parts[i_date])
        if week is None:
            # 資料日期 無法解析的列跳過——不產出 (ticker, None) 這種無效聚合鍵
            # （week 是 major_holders 的 PK，不可為 None）。
            continue
        saw_valid_week = True
        key = (ticker, week)
        entry = agg.get(key)
        if entry is None:
            entry = agg[key] = {"ratio_400up": 0.0, "holder_count": None}
            order.append(key)

        level = parts[i_level].strip()
        if level in _RATIO_400UP_LEVELS:
            ratio = _common.to_number(parts[i_ratio])
            if ratio is not None:
                entry["ratio_400up"] += ratio
        if level in _HOLDER_LEVELS:
            people = _common.to_int(parts[i_people])
            if people is not None:
                entry["holder_count"] = (entry["holder_count"] or 0) + people

    if saw_wanted and not saw_valid_week:
        # 有想要的列、卻沒有任何一列日期可解析 → 資料日期欄結構漂移，raise 讓人工
        # 確認，而非回空（比照 bad-header / empty-input 的「不靜默空解析」原則）。
        raise SourceFetchError(
            SOURCE, f"{SOURCE} 資料來源日期欄位無法解析，請人工確認"
        )

    return [
        {
            "ticker": ticker,
            "week": week,
            "ratio_400up": agg[(ticker, week)]["ratio_400up"],
            "holder_count": agg[(ticker, week)]["holder_count"],
        }
        for ticker, week in order
    ]
