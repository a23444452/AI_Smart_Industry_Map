# 切片 6：公司資料庫＋個股頁 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成 `/companies`（公司資料庫：搜尋/題材篩選/分頁表格）與 `/c/{ticker}`（個股頁：報價頭部＋K 線＋本益比河流圖＋法人買賣超副圖＋大戶持股比例），含基本面/PER/集保資料管線。

**Architecture:** 延續方案 A。新增 3 張表（fundamentals／per_daily／major_holders）與 4 條資料來源；四種圖表由既有＋新表組裝；前端新增兩頁與四個 ECharts 圖表元件。

**Tech Stack:** 既有棧（**不用 FinMind**——見決策 1）

**Spec:** `docs/superpowers/specs/2026-07-11-ai-stock-map-clone-design.md` §3（fundamentals/major_holders）、§4（fetch_fundamentals/fetch_tdcc_holders）、§5（companies API 三端點）、§6（兩頁）

**執行模式：** 同前。分支 `feat/slice-6`。

## 決策（有意識偏離）

1. **不用 FinMind，全走 TWSE/TPEx OpenAPI**：spec §3 原定 FinMind 供 fundamentals，但 TWSE OpenAPI 已涵蓋——月營收 `t187ap05_L`（上市）/TPEx `mopsfin_t187ap05_O`（上櫃）、每日 PER/殖利率/PBR `BWIBBU_ALL`（上市）/TPEx 對應資料集。免 token、免額度管理、與既有六支 source 同模式。EPS 不另抓：河流圖用 `EPS_ttm = close ÷ PER` 反推（BWIBBU 的 PER 即 TTM 口徑）。
2. **本益比河流圖資料**：`per_daily` 存每日 PER/PBR/殖利率；歷史用 TWSE `rwd/BWIBBU`（個股月檔）backfill 3 個月（與行情 backfill 同模式）。河流帶＝當日反推 EPS × 歷史 PER 分位（P10/P25/P50/P75/P90，後端算好給前端）。
3. **TDCC 集保**：官方 open data CSV（`https://opendata.tdcc.com.tw/getOD.ashx?id=1-5`，週更、全市場股權分散表）。下載後過濾已收錄 ticker；`ratio_400up`＝持股 >400 張級距的佔比合計（級距定義以實錄為準）。CSV 大（數十 MB）——streaming 解析、只留需要列。
4. **公司資料庫篩選用「所屬題材」**（join topic_companies）而非 industry_tags（該欄目前無資料）；搜尋比對 ticker/name。
5. **個股頁視覺以 spec §6 清單為準**：原站個股頁在登入牆後未盤點——功能骨架先行，像素級比對留待使用者提供截圖後打磨（不阻塞）。
6. **K 線資料就用 quotes_daily 現有歷史**（backfill 已有 ~48 交易日/檔；本切片把 `_MAX_MONTHS` 上限 3→6 讓 K 線更完整，順手）。
7. **順手打磨**（切片 5 minors）：MoversRanking 標題改「強勢股排行」。

## 資料來源（fixtures-first，URL 為假設、以實錄為準）

| Source | 端點假設 | 排程 |
|--------|----------|------|
| `twse_revenue`/`tpex_revenue` | `openapi.twse.com.tw/v1/opendata/t187ap05_L`／`tpex mopsfin_t187ap05_O`（list[dict]，當月全市場） | 每月 11/12 日 08:30 |
| `twse_per`（全市場當日） | `openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL` | 平日 15:00 |
| `tpex_per` | TPEx openapi PER 資料集（探索：`tpex_mainboard_peratio_analysis` 或同類；不行再用 rwd 端點） | 同上 |
| `twse_per_history`（個股月檔，backfill 用） | `www.twse.com.tw/rwd/zh/afterTrading/BWIBBU?date={YYYYMM01}&stockNo={t}&response=json`（上櫃對應端點探索；找不到 → 上櫃河流圖降級為僅日更累積，報告說明） | — |
| `tdcc_holders` | `opendata.tdcc.com.tw/getOD.ashx?id=1-5`（CSV，streaming） | 週六 09:30 |

---

## File Structure（新增/修改重點）

```
backend/
├── app/db/models.py               # ＋Fundamental/PerDaily/MajorHolder
├── app/pipeline/sources/          # ＋twse_revenue.py/tpex_revenue.py/twse_per.py/tpex_per.py
│                                  #   /twse_per_history.py/tdcc_holders.py
├── app/pipeline/jobs_daily.py     # ＋fetch_per
├── app/pipeline/jobs_monthly.py   # 新：fetch_fundamentals/fetch_tdcc（低頻 job 歸檔）
├── app/pipeline/jobs_backfill.py  # ＋backfill_per；_MAX_MONTHS 3→6
├── app/pipeline/scheduler.py      # ＋三組 cron
├── app/api/companies.py           # 三端點（list/detail/charts）
└── tests/…
frontend/src/
├── api/companies.ts
├── charts/KLine.tsx / PerRiver.tsx / InstitutionalBars.tsx / HoldersLine.tsx
│   （共用 chartsCore.ts：echarts.use 註冊集中——candlestick/line/bar 元件）
├── pages/CompaniesPage.tsx / CompanyPage.tsx
├── components/company/QuoteHeader.tsx / CompanyTable.tsx
└── App.tsx / NavBar.tsx           # /companies、/c/:ticker、NavBar 公司資料庫啟用
```

---

### Task 1: 三張表

**Files:** Modify: `backend/app/db/models.py`, `backend/tests/test_models.py`

- [ ] 失敗測試→實作→綠：
  - `Fundamental`：ticker＋month（"2026-06"）複合 PK、revenue（BigInteger 千元）、yoy（Float nullable）
  - `PerDaily`：ticker＋date 複合 PK、per/pbr/dividend_yield（Float nullable）
  - `MajorHolder`：ticker＋week（ISO date str，資料日）複合 PK、ratio_400up（Float）、holder_count（Integer nullable，總集保戶數）
- [ ] Commit：`feat: 基本面三張表`

### Task 2: 營收 sources（上市/上櫃，fixtures-first）

**Files:** Create: `twse_revenue.py`, `tpex_revenue.py`＋fixtures；Modify: `record_fixtures.py`, `test_sources.py`

- [ ] 錄製（欄位以實錄為準；月營收 OpenAPI 為 list[dict] 中文/英文 key 以實錄）→ 失敗測試（`parse(raw)` → `{ticker, month("YYYY-MM"), revenue(千元 int), yoy(float|None)}`；民國年月轉換；缺欄容忍）→ 實作 → 綠
- [ ] Commit：`feat: 月營收 sources`

### Task 3: PER sources（當日全市場＋個股歷史，fixtures-first）

**Files:** Create: `twse_per.py`, `tpex_per.py`, `twse_per_history.py`＋fixtures；Modify: `record_fixtures.py`, `test_sources.py`

- [ ] 錄製三端點（TPEx PER 資料集需探索；per_history 月檔同 STOCK_DAY 模式含 rate limit sleep）→ 失敗測試（`parse` → `{ticker, date, per, pbr, dividend_yield}`；「-」/空→None；漂移守衛）→ 實作 → 綠
- [ ] Commit：`feat: PER sources`

### Task 4: TDCC 集保 source（CSV streaming）

**Files:** Create: `tdcc_holders.py`＋fixture（截斷樣本）；Modify: `record_fixtures.py`, `test_sources.py`

- [ ] 錄製（**fixture 只存標頭＋已收錄 ticker 的列＋幾列雜訊**，完整檔數十 MB 不入 repo）→ 失敗測試：`parse(csv_text, wanted: set[str])` → `{ticker, week(資料日期 ISO), ratio_400up, holder_count}`——級距欄以實錄為準（>400 張＝400,001 股以上各級距佔比合計）；驗算一檔：各級距佔比合計≈100%
- [ ] 實作：`fetch()` streaming（httpx `iter_bytes`/`iter_lines`，避免整檔入記憶體；**這是專案第一個 CSV source**——編碼以實錄為準，可能 UTF-8 BOM 或 Big5）→ 綠
- [ ] Commit：`feat: TDCC 集保 source`

### Task 5: jobs＋scheduler＋backfill

**Files:** Modify: `jobs_daily.py`, `jobs_backfill.py`, `scheduler.py`, `cli.py`＋tests；Create: `jobs_monthly.py`

- [ ] 失敗測試 → 實作 → 綠：
  - `fetch_per(session)`：兩市場當日 → 過濾已收錄 → upsert per_daily；單來源隔離（比照 fetch_market_stats）
  - `fetch_fundamentals(session)`：兩市場當月營收 → 過濾 → upsert fundamentals
  - `fetch_tdcc(session)`：CSV → 過濾 → upsert major_holders
  - `backfill_per(session, months=3)`：逐檔 per_history（單檔失敗 skip；上櫃無歷史端點時跳過並 log——見決策 2）
  - `_MAX_MONTHS` 3→6（quotes backfill；對應測試調整）
  - cron：`fetch_per` 平日 15:00；`fetch_fundamentals` 每月 11,12 日 08:30（兩發）；`fetch_tdcc` 週六 09:30
  - cli backfill 加 backfill_per
- [ ] **實跑** `make backfill`（quotes 6 月＋per 3 月）＋手動跑 fetch_per/fetch_fundamentals/fetch_tdcc，sqlite3 驗證三張新表，附報告
- [ ] Commit：`feat: 基本面資料管線`

### Task 6: companies API 三端點

**Files:** Create: `backend/app/api/companies.py`, `backend/tests/test_api_companies.py`；Modify: `main.py`

- [ ] 失敗測試 → 實作 → 綠：
  1. `GET /api/companies?query=&topic=&page=1&page_size=20` → `{total, page, page_size, items: [{ticker,name,market,topics:[slug],close,change_pct,per,revenue_yoy}]}`——query 比對 ticker 前綴/name 包含；topic 篩選 join topic_companies；分頁；固定查詢數
  2. `GET /api/companies/{ticker}` → 報價頭部聚合 `{ticker,name,market,close,change,change_pct,volume,topics:[{slug,title}],badges,per,pbr,dividend_yield,latest_revenue:{month,revenue,yoy},major_holder:{week,ratio_400up},quotes_updated_at(Z)}`；404 統一格式
  3. `GET /api/companies/{ticker}/charts/{kind}`：
     - `kline` → `{items:[{date,open,high,low,close,volume}]}`（依 date 升冪）
     - `per_river` → `{items:[{date,close,band_p10,band_p25,band_p50,band_p75,band_p90}]}`（帶＝EPS_ttm(當日)×歷史 PER 分位；PER 缺→該日帶 null；**分位以該 ticker per_daily 全期計算**）
     - `institutional` → `{items:[{date,foreign_net,trust_net,dealer_net}]}`（近 60 日）
     - `holders` → `{items:[{week,ratio_400up}]}`（升冪）
     - 未知 kind → 422（Literal）；無資料 → items []
- [ ] Commit：`feat: companies API`

### Task 7: 前端圖表四元件

**Files:** Create: `frontend/src/charts/chartsCore.ts`, `KLine.tsx`, `PerRiver.tsx`, `InstitutionalBars.tsx`, `HoldersLine.tsx`＋轉換純函式測試（每圖表一個 `toXxxOption` 或資料轉換函式可測）；Modify: `charts/Treemap.tsx`（改用 chartsCore 註冊，去重複）

- [ ] `chartsCore.ts`：集中 `echarts.use([...])`（Treemap/Candlestick/Line/Bar/Grid/Axis/Tooltip/Legend/DataZoom/Canvas）＋共用深色 axis/tooltip 樣式（theme.ts 色）＋`useEChart` hook（init/dispose/resize——抽自 Treemap 現有邏輯）
- [ ] 四元件：KLine（candlestick 紅漲綠跌＋成交量副圖＋dataZoom）、PerRiver（close 線＋五條帶線漸層區域）、InstitutionalBars（三色柱＋零軸）、HoldersLine（週線＋面積）
- [ ] 純函式測試 ≥8 case（K 線 OHLC 映射與紅綠、river null 帶處理、bars 正負色、holders 排序）；**全部 lazy-load 準備**（元件 default export）
- [ ] Commit：`feat: 個股圖表元件`

### Task 8: 兩頁＋路由

**Files:** Create: `frontend/src/api/companies.ts`, `pages/CompaniesPage.tsx`, `pages/CompanyPage.tsx`, `components/company/QuoteHeader.tsx`, `CompanyTable.tsx`＋測試；Modify: `App.tsx`（兩 route＋圖表 lazy）、`NavBar.tsx`（公司資料庫啟用）；順手: MoversRanking 標題改「強勢股排行」

- [ ] `api/companies.ts`（**L1 nullability 對照後端**）＋useCompanies(query,topic,page)/useCompany(ticker)/useCompanyChart(ticker,kind)
- [ ] CompaniesPage：搜尋框（debounce 300ms）＋題材下拉（**注意：useTopics 是單市場焦點導向 hook，不適用**——後端 companies list 端點順帶回傳 `topics_facets: [{slug,title}]` 全題材清單供下拉，或前端另打 5 個 market 合併，擇一（建議前者，Task 6 補此欄位））＋表格（ticker/name/close/change_pct/per/yoy、列點擊 → /c/{ticker}）＋分頁 controls＋四態
- [ ] CompanyPage `/c/:ticker`：QuoteHeader（name/ticker/close 大字/change 帶色/volume/PER/PBR/殖利率/營收 YoY/大戶比/題材 chips 連 /topic/{slug}）＋四圖表區（lazy＋Suspense、各自 useCompanyChart、空資料佔位）＋404 專頁
- [ ] MoversRanking 列點擊 → `/c/{ticker}`（每日焦點連個股頁，順手）；元件測試 ≥8 case；vitest 全綠＋build 綠
- [ ] Commit：`feat: 公司資料庫與個股頁`

### Task 9: 端到端驗證＋README

- [ ] 全測試實跑 → `make dev`＋curl 三端點＋兩頁 200 → 殺乾淨 → README（API 表三端點、切片 1-6 狀態、TDCC/營收/PER 資料來源）→ Commit：`docs: README 切片 6`

---

## 驗收條件

1. `/companies` 可搜尋/篩選/分頁，列點擊進個股頁
2. `/c/2330` 顯示真實報價頭部＋四圖表（K 線 6 個月、河流圖 3 個月、法人 60 日、大戶週線）
3. 三組新 cron 註冊；`make backfill` 含 PER
4. 全測試綠；品質底線；echarts 仍為獨立 chunk（新圖表併入同 chunk）

## 注意事項（給實作 subagent）

- **L1 教訓必守**（前端型別逐欄對照後端 Pydantic）
- fixtures 先於 parser（六個新端點）；TDCC CSV 注意編碼與檔案大小（fixture 截斷）
- runner／UTC+Z／ApiError／假日空/漂移 raise 契約沿用
- 原站個股頁未盤點——不要臆測像素細節，按本計畫結構做，打磨後補
- 河流圖分位在後端算（前端拿到即畫），計算需防 **PER 為 None 或 0**（除零——該日帶全 null）/資料 <10 筆（帶全 null）
