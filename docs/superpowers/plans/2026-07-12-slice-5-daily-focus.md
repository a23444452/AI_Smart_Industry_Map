# 切片 5：每日焦點 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成 `/`（每日焦點頁）——指數行情卡列、三大法人（市場層）、資券變化、強勢股排行（日/週/月）、MOPS 重大訊息時間軸，含對應資料管線。

**Architecture:** 延續方案 A。新增 4 張表（index_snapshots／market_flows／margin_balances／mops_announcements）與 4 條資料來源（Yahoo 指數、TWSE 三大法人金額統計、TWSE 資券、MOPS 重大訊息）；強勢股由 quotes_daily 即時計算。前端新首頁 DailyPage。

**Tech Stack:** 既有棧（指數用 Yahoo v8 chart HTTP API 直打，**不加 yfinance 依賴**——與既有 httpx/_common 模式一致）

**Spec:** `docs/superpowers/specs/2026-07-11-ai-stock-map-clone-design.md` §3（四張表）、§4（fetch_indices/fetch_margin/fetch_mops）、§5（GET /api/daily）、§6（每日焦點頁）

**執行模式：** 同前——Opus 4.8 實作＋審查；同 task 連續失敗 2 次回報主對話。分支 `feat/slice-5`。

## 決策（有意識偏離）

1. **指數改用現貨**：台指期改「加權指數 ^TWII」（Yahoo 期貨符號不穩定）；覆蓋 ^TWII／^SOX 費半／^GSPC S&P500／TSM ADR／NVDA／^N225 日經／^VIX 共 7 檔；原站的「韓國綜合(EWY)」省略。
2. **強勢股排行限「已收錄公司」universe**（目前 17 檔）：quotes_daily 只存已收錄公司（既有設計），全市場排行需存全市場行情——等公司資料庫（切片 6）擴 universe 後自然變大。UI 註明「排行範圍：已收錄個股」。
3. **市場層三大法人另建 `market_flows` 表**：spec §3 原設計 institutional_flows 的 ticker 可空＝市場層，但該表 ticker 是複合 PK 不可空——分表較乾淨（date+unit PK）。
4. **不做**（spec 既定排除）：Podcast/新聞編輯內容、主動式 ETF、大戶加碼股（需集保，切片 6）、Premium 鎖。
5. **併入 follow-ups（#35 的可自動化項）**：`db.base._utcnow` 公開化為 `utcnow`（Task 1 順手）；CategoryBlock placeholder 不顯示「0 家公司」pill（Task 6 順手）。404 宣告去重不做（/api/daily 無 404 pattern，未達第三次）。

## 資料來源（fixtures-first，URL 為假設、以實錄為準）

| Source | 端點假設 | 排程 |
|--------|----------|------|
| `yahoo_indices` | `https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1d`（每 symbol 一請求，需 UA header） | 平日每 15 分（08:00-22:00 台北） |
| `twse_bfi82u`（三大法人金額統計） | `https://www.twse.com.tw/rwd/zh/fund/BFI82U?dayDate={YYYYMMDD}&type=day&response=json` | 平日 16:20、17:20 |
| `twse_margin`（資券餘額） | `https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date={YYYYMMDD}&selectType=MS&response=json`（市場彙計） | 平日 21:40 |
| `twse_mops`（重大訊息） | TWSE OpenAPI `https://openapi.twse.com.tw/v1/opendata/t187ap04_L`（上市當日重大訊息；上櫃對應 `t187ap04_O`——於 openapi.tpex.org.tw 或同站，實測擇一） | 每日 19:10 |

---

## File Structure

```
backend/
├── app/db/models.py               # ＋IndexSnapshot/MarketFlow/MarginBalance/MopsAnnouncement
├── app/db/base.py                 # _utcnow → utcnow（保留底線別名相容）
├── app/pipeline/sources/
│   ├── yahoo_indices.py / twse_bfi82u.py / twse_margin.py / mops.py
├── app/pipeline/jobs.py           # ＋fetch_indices/fetch_market_stats/fetch_mops
├── app/pipeline/jobs_backfill.py  # ＋backfill_market_stats（法人/資券 30 日）
├── app/pipeline/scheduler.py      # ＋三組 cron
├── app/api/daily.py               # GET /api/daily＋/api/daily/announcements
└── tests/…（fixtures＋測試）
frontend/src/
├── api/daily.ts
├── pages/DailyPage.tsx            # route "/"
├── components/daily/IndexCards.tsx / MarketFlowsTable.tsx / MarginTable.tsx
│                    / MoversRanking.tsx / MopsTimeline.tsx（＋__tests__）
├── components/map/CategoryBlock.tsx  # placeholder pill 修（順手）
└── App.tsx / components/layout/NavBar.tsx  # 每日焦點啟用、/ → DailyPage
```

---

### Task 1: 四張表＋utcnow 公開化

**Files:** Modify: `backend/app/db/models.py`, `backend/app/db/base.py`, `backend/app/api/queries.py`（import 改名）, `backend/tests/test_models.py`

- [ ] **Step 1:** 失敗測試：建表含四張新表；各一 roundtrip：
  - `IndexSnapshot`：id auto PK、symbol、name、price float、change float nullable、change_pct float nullable、fetched_at datetime——**只留每 symbol 最新一筆的策略：upsert by symbol**（symbol 設 unique；歷史不留，MVP 只要跑馬燈現值）→ 改用 symbol 為 PK 更簡單，採之
  - `MarketFlow`：date＋unit（自營商/自營商避險/投信/外資及陸資/外資自營商）複合 PK、buy/sell/net（bigint 元）
  - `MarginBalance`：date＋item（融資餘額/融券餘額/融資金額…）複合 PK、buy/sell/prev_balance/today_balance（bigint，缺欄容忍 null）
  - `MopsAnnouncement`：id auto PK、ticker、name、category（**統一長格式**：澄清回應/自結/財務數據/公司治理/重大事件——規則分類欄，與 Task 4/6/7 一致）、title Text、published_at（datetime naive UTC）＋`(ticker, title, published_at)` unique constraint 防重複匯入
- [ ] **Step 2:** FAIL → **Step 3:** 實作；`base.py` `_utcnow` 改名 `utcnow`（模組層 `_utcnow = utcnow` 別名保留相容，避免大面積改動；queries.py 改用新名）
- [ ] **Step 4:** 全綠 → **Step 5:** Commit：`feat: 每日焦點四張表`

---

### Task 2: Yahoo 指數 source（fixtures-first）

**Files:** Create: `backend/app/pipeline/sources/yahoo_indices.py`＋fixtures；Modify: `record_fixtures.py`, `test_sources.py`

- [ ] **Step 1:** 錄製：7 symbols 各打 `v8/finance/chart/{symbol}?interval=1d&range=1d`（**需瀏覽器型 `User-Agent` header 否則 429**——既有 `get_json_dict` 的 UA 寫死為 aism/1.0，需參數化 headers 或本 source 自建 fetch，實作者擇一；sleep 0.5/請求）；存 ^TWII 與 NVDA 兩份 fixture＋一份錯誤 symbol 回應
- [ ] **Step 2:** 失敗測試：`parse(raw, symbol)` → `{symbol, name, price, change, change_pct}`——price=`meta.regularMarketPrice`、prev=`meta.chartPreviousClose`（欄位以實錄為準）、change/change_pct 計算＋除零防護；壞回應（chart.error 非 null）→ raise SourceFetchError；`SYMBOLS` 常數表（symbol→中文名：加權指數/費城半導體/S&P 500/台積電 ADR/輝達 NVDA/日經 225/VIX 恐慌）
- [ ] **Step 3:** FAIL → **Step 4:** 實作（`fetch(symbol)` 帶 UA＋rate limit 常數；沿用 `get_json_dict`）→ **Step 5:** 全綠；Commit：`feat: Yahoo 指數 source`

---

### Task 3: TWSE 市場統計 sources（法人＋資券，fixtures-first）

**Files:** Create: `backend/app/pipeline/sources/twse_bfi82u.py`, `twse_margin.py`＋fixtures；Modify: `record_fixtures.py`, `test_sources.py`

- [ ] **Step 1:** 錄製兩端點（交易日＋假日各一）；人工檢視欄位
- [ ] **Step 2:** 失敗測試：
  - `twse_bfi82u.parse(raw, date)` → list of `{unit, buy, sell, net, date}`（單位「元」；unit 名稱以實錄為準——原始為自營商(自行買賣)/自營商(避險)/投信/外資及陸資(不含外資自營商)/外資自營商）
  - `twse_margin.parse(raw, date)` → list of `{item, buy, sell, prev_balance, today_balance, date}`（MS 彙計表：融資交易張/融券交易張/融資金額仟元——以實錄為準）
  - 假日→[]；欄位漂移→raise（用 `resolve_field_index`）
- [ ] **Step 3:** FAIL → **Step 4:** 實作 → **Step 5:** 全綠；Commit：`feat: TWSE 市場統計 sources`

---

### Task 4: MOPS 重大訊息 source（fixtures-first）

**Files:** Create: `backend/app/pipeline/sources/mops.py`＋fixtures；Modify: `record_fixtures.py`, `test_sources.py`

- [ ] **Step 1:** 錄製 t187ap04_L（上市）；探索上櫃對應端點（t187ap04_O 或 TPEx openapi），二者皆錄；**注意 OpenAPI 格式是 list[dict]（用既有 `get_json`）**
- [ ] **Step 2:** 失敗測試：`parse(raw)` → list of `{ticker, name, title, published_at(datetime naive UTC——來源日期時間欄轉換，注意 ROC 日期＋HH:MM:SS), category}`；**分類規則**（`classify(title) -> str`，獨立純函式）：含「澄清」→澄清回應；含「自結」→自結；含「財務報告/財報」→財務數據；含「董事會/股東會/治理/獨立董事」→公司治理；其餘→重大事件。規則測試至少 6 例
- [ ] **Step 3:** FAIL → **Step 4:** 實作 → **Step 5:** 全綠；Commit：`feat: MOPS 重大訊息 source`

---

### Task 5: jobs＋scheduler＋backfill

**Files:** Modify: `backend/app/pipeline/jobs.py`, `jobs_backfill.py`, `scheduler.py`, `cli.py`, 對應測試

- [ ] **Step 1:** 失敗測試（monkeypatch sources）：
  1. `fetch_indices(session)`：7 symbols 逐一 fetch+parse → upsert `index_snapshots`（symbol PK 覆寫、fetched_at=now）；**單 symbol 失敗 skip＋log**（指數卡缺一張比整批失敗好），全失敗 → raise 讓 runner 記 failed
  2. `fetch_market_stats(session)`：bfi82u＋margin（台北今日）→ upsert market_flows/margin_balances；假日空→無寫入仍 success；**兩來源互相隔離**——margin 未公布/失敗不可影響已 stage 的 flows（各自 try/except，單來源失敗 log warning、兩者皆失敗才 raise 給 runner 重試）；錄 fixture 時確認「下午時段 MI_MARGN 未公布」的回應形態（預期空資料集→視同假日，非 error）
  3. `fetch_mops(session)`：兩市場 → 過濾？**不過濾**（重大訊息全市場皆收——公告對象不限已收錄公司；上限保護：單日 >500 筆時只取前 500＋log warning）→ insert（unique constraint 冪等，重複 skip）
  4. `backfill_market_stats(session, days=30)`：逐日 bfi82u＋margin；單日失敗 skip
  5. scheduler 新 cron：indices（`*/15 8-22 * * mon-fri`）、market_stats（16:20/17:20）、margin 併入 market_stats？——**margin 21:40 獨立一發**（資料公布時間不同）：`fetch_market_stats` 拆 flows 與 margin 兩個 job？**採單一 job `fetch_market_stats` 排 16:20/17:20/21:45 三發**（冪等 upsert，資券在晚間那發補上）——簡單優先
  6. cli backfill 擴充：加跑 backfill_market_stats
- [ ] **Step 2:** FAIL → **Step 3:** 實作（runner 契約沿用）→ **Step 4:** 全綠
- [ ] **Step 5:** **實跑**：`make backfill`（含新 job）＋手動 `run_job` 跑一次 fetch_indices/fetch_mops，sqlite3 驗證四張表有資料，輸出附報告；Commit：`feat: 每日焦點資料管線`

---

### Task 6: GET /api/daily＋announcements

**Files:** Create: `backend/app/api/daily.py`, `backend/tests/test_api_daily.py`；Modify: `backend/app/main.py`；順手: `frontend/src/components/map/CategoryBlock.tsx`（placeholder 不顯示 0 家公司 pill＋測試調整）

- [ ] **Step 1:** 失敗測試：
  1. `GET /api/daily` → 
     ```json
     {
       "indices": [{"symbol","name","price","change","change_pct","fetched_at(Z)"}],
       "market_flows": {"date", "rows": [{"unit","buy","sell","net"}]},
       "margin": {"date", "rows": [{"item","buy","sell","prev_balance","today_balance"}]},
       "movers": {"day": [...], "week": [...], "month": [...]},   // 每項 [{ticker,name,close,change_pct}] 依 change_pct 降冪 top 30、universe=已收錄
       "announcements_dates": ["2026-07-11", ...]                  // 近 7 個有公告的日期
     }
     ```
     movers 的 week/month 重用 `app/api/topics.py` 的 `_period_change(rows, offset)`（建議抽到 queries.py 公開化）；注意 `quotes_by_ticker` 收明確 tickers 清單（topic 範圍），movers 需要全 quotes_daily universe——另寫 distinct-ticker 查詢，offset 計算共用 `_period_change`
  2. `GET /api/daily/announcements?date=YYYY-MM-DD&category=澄清回應`（category optional）→ `[{ticker,name,category,title,published_at(Z)}]` 依 published_at 降冪；date 必填、格式錯 422
  3. 空表全部不炸（indices [] 等）
- [ ] **Step 2:** FAIL → **Step 3:** 實作（Pydantic models；固定查詢數；datetime 用 serializers）→ **Step 4:** 全綠 → **Step 5:** 實跑 curl 附報告；Commit：`feat: daily API`

---

### Task 7: DailyPage 前端

**Files:** Create: `frontend/src/api/daily.ts`, `frontend/src/pages/DailyPage.tsx`, `frontend/src/components/daily/`（IndexCards/MarketFlowsTable/MarginTable/MoversRanking/MopsTimeline＋__tests__ 至少 8 case）；Modify: `frontend/src/App.tsx`（`/` → DailyPage、移除 redirect）、`frontend/src/components/layout/NavBar.tsx`（每日焦點啟用為 NavLink）

- [ ] **Step 1:** `api/daily.ts` 型別（**L1：nullability 逐欄對齊後端 Pydantic**）＋`useDaily()`（refetchInterval 60s）＋`useAnnouncements(date, category?)`
- [ ] **Step 2:** 失敗元件測試：
  - IndexCards：7 張小卡（name、price 千分位、change_pct 紅漲綠跌帶符號；null → --）
  - MarketFlowsTable：五身份列＋買/賣/買賣超（億元格式化 `formatYi`：元→億 保留 0-1 位小數）；淨額紅正綠負
  - MarginTable：資券列（張/仟元單位標註）
  - MoversRanking：日/週/月 tabs（aria-pressed）、排名列（#1-N、ticker/name/close/change_pct）、「排行範圍：已收錄個股」註記
  - MopsTimeline：日期 tabs（announcements_dates）＋分類 chips（全部/澄清回應/自結/財務數據/公司治理/重大事件——chip 切換 category 參數）＋公告卡（category chip、title、ticker name、時間台北格式）
- [ ] **Step 3:** FAIL → **Step 4:** 實作（深色 tokens、四態沿用既有模式、DataFreshness 掛 indices fetched_at）→ **Step 5:** vitest 全綠＋build 綠；Commit：`feat: 每日焦點頁`

---

### Task 8: 端到端驗證＋README

**Files:** Modify: `README.md`

- [ ] 全測試實跑 → `make dev`＋curl `/api/daily`（indices 7 檔、movers 非空）＋前端 `/` 200 → 殺乾淨 → README（API 表、切片 1-5 狀態、指數來源與延遲註記）→ Commit：`docs: README 切片 5`

---

## 驗收條件

1. `/` 顯示：7 張指數卡（真實延遲報價）、三大法人表（真實市場資料）、資券表、強勢股排行（日/週/月、已收錄 universe）、MOPS 時間軸（真實公告＋分類篩選）
2. 排程：indices 每 15 分（平日 08-22）、market_stats 三發、mops 19:10 皆註冊
3. 全測試綠；品質底線同前
4. NavBar「每日焦點」啟用且為預設首頁

## 注意事項（給實作 subagent）

- **L1 教訓（必守）**：前端 TS 型別誠實對齊後端 Pydantic nullability，nullable 欄位顯式 fallback＋null 測試
- fixtures 先於 parser（四個新端點都要實錄，交易日＋假日）；Yahoo 需 UA header
- 單位注意：BFI82U 是「元」、MI_MARGN 彙計表混合「張」與「仟元」——parse 保留原始單位＋欄位註明，換算（億元顯示）放前端 formatter
- MOPS 公告不過濾已收錄公司（全市場收）；title 可能極長——DB Text、前端 line-clamp
- runner/UTC(Z)/ApiError 契約沿用
