# AI 智慧產業地圖

以投資題材為軸，串接台股產業鏈、公司清單與每日收盤漲跌，一頁看懂 AI 時代的關鍵產業脈絡。

## 功能總覽

- **每日焦點頁**（`/`）：七檔指數快照、三大法人買賣金額、資券餘額、日／週／月強勢股排行、MOPS 重大訊息時間軸。
- **題材總覽頁**（`/topics`）：題材卡片與排行，含成分股家數與平均漲跌。
- **題材詳情頁**（`/topic/:slug`）：ECharts treemap 三週期熱力圖、籌碼訊號。
- **產業地圖頁**（`/topic/:slug/map`）：供應鏈上／中／下游分層，公司卡片標角色、關聯度、收盤漲跌與籌碼徽章。
- **公司資料庫頁**（`/companies`）：代號／名稱搜尋、題材篩選、分頁。
- **個股頁**（`/c/:ticker`）：報價、估值、題材、籌碼、月營收、集保大戶持股，四張 ECharts 圖表（K 線／本益比河流／三大法人／集保分散）。
- **AI 分析頁**（`/ai`）：觸發個股五面向 AI 評分、評分排行榜（強勢／弱勢切換）。
- **全站搜尋（⌘K）**：任一頁按 `⌘K`（macOS）／`Ctrl+K`（Windows／Linux）開啟命令面板，跨公司與題材即時檢索，方向鍵選取、Enter 直達，Esc 關閉。

## 架構

```
   TWSE / TPEx           ┌──────────────────────┐
   Yahoo Finance ──────▶ │   pipeline（抓取）    │
   MOPS                  │  runner + jobs +     │
   （行情/法人/公告）      │  APScheduler 排程     │
                         └──────────┬───────────┘
                                    │ upsert
                                    ▼
   ┌────────────┐   HTTP    ┌──────────────┐   ORM    ┌──────────────┐
   │  frontend  │ ───────▶  │     API      │ ───────▶ │    SQLite    │
   │ React+Vite │ ◀───────  │   FastAPI    │ ◀─────── │   aism.db    │
   └────────────┘   JSON    └──────────────┘  query   └──────────────┘
   :5173                     :8000
```

- **pipeline** 從各資料來源抓取行情／法人／公告，經 runner 冪等 upsert 進 SQLite；APScheduler 定時排程。
- **API**（FastAPI）讀 SQLite，對前端提供題材／每日焦點／公司／AI 分析／搜尋等 JSON 端點。
- **frontend**（React + Vite）呼叫 API，渲染每日焦點、題材總覽、產業地圖、公司資料庫、個股頁與 AI 分析六大頁面。

### 資料來源

| 來源 | 內容 | 備註 |
|------|------|------|
| TWSE / TPEx | 台股收盤行情、三大法人買賣超、法人買賣金額（BFI82U）、信用交易餘額、個股月營收、本益比／殖利率（BWIBBU／peratio） | 官方 OpenAPI |
| TDCC 集保結算所 | 個股股權分散表（>400 張大戶持股比） | 每週更新（週六抓取） |
| Yahoo Finance | 每日焦點指數列（加權、費半、S&P 500、TSM、NVDA、日經、VIX） | 延遲報價，僅供參考，非即時行情 |
| MOPS 公開資訊觀測站 | 上市／上櫃重大訊息公告 | 每日抓取當日公告（含假日） |

## 快速開始

需求：Python 3.12+、[uv](https://docs.astral.sh/uv/)、Node.js 20+。

```bash
cp .env.example .env       # 建立環境變數
make seed                  # 匯入題材 seeds（矽光子）
make fetch                 # 抓取台股收盤資料
make backfill              # 回填歷史行情、三大法人與市場統計
make dev                   # 同時啟動後端(:8000) 與前端(:5173)
```

啟動後開啟 <http://localhost:5173/> 檢視每日焦點，<http://localhost:5173/topics> 檢視題材總覽，<http://localhost:5173/companies> 檢視公司資料庫，<http://localhost:5173/ai> 檢視 AI 分析與評分榜。

## 指令表（`make help`）

| 指令 | 說明 |
|------|------|
| `make help` | 顯示可用指令清單 |
| `make seed` | 匯入題材 seeds（`data/seeds/*.yaml` → SQLite） |
| `make fetch` | 抓取台股收盤資料並寫入 DB |
| `make backfill` | 回填歷史行情（近 6 個月，每檔 ≥100 交易日）、三大法人買賣超（近 14 日）、市場統計（法人金額＋資券餘額，近 30 日）與本益比歷史（近 3 個月） |
| `make dev` | 以 `make -j2` 同時啟動後端＋前端開發伺服器 |
| `make dev-backend` | 只啟動後端（FastAPI，port 8000） |
| `make dev-frontend` | 只啟動前端（Vite，port 5173） |
| `make test` | 執行後端（pytest）與前端（vitest）測試 |

## API

| 方法 | 路徑 | 說明 |
|------|------|------|
| GET | `/healthz` | 健康檢查 |
| GET | `/api/topics?market=tw` | 題材清單＋排行（含 company_count、change_pct_avg） |
| GET | `/api/topics/{slug}` | 單一題材詳情（metrics、treemap 三週期漲跌、chip_signals 籌碼訊號、quotes_updated_at） |
| GET | `/api/topics/{slug}/map` | 產業地圖：供應鏈分層（上游／中游／下游）、各分類公司卡（角色、關聯度、收盤漲跌、籌碼徽章），下游含 placeholder 分類 |
| GET | `/api/daily` | 每日焦點聚合：indices 指數快照（7 檔）、market_flows 三大法人金額、margin 資券餘額、movers 強勢股（日／週／月）、announcements_dates 公告日期列表 |
| GET | `/api/daily/announcements?date=YYYY-MM-DD` | 指定日期的 MOPS 重大訊息公告列（台北時區） |
| GET | `/api/companies?query=&topic=&page=1&page_size=20` | 公司清單：代號前綴／名稱搜尋、題材 slug 篩選、分頁；含 total、page_size、topics_facets 全題材列 |
| GET | `/api/companies/{ticker}` | 個股詳情：報價、估值（PER／PBR／殖利率）、題材、籌碼徽章、最新月營收、集保大戶持股比 |
| GET | `/api/companies/{ticker}/charts/{kind}` | 個股圖表資料（`kind` ∈ `kline`／`per_river`／`institutional`／`holders`），回傳 `items` 陣列 |
| GET | `/api/search?q=` | 全站搜尋（⌘K 命令面板）：公司（ticker 前綴／name 包含）與題材（title 包含／slug 前綴）各取前 10，回傳 `{companies, topics}`；`q` 必填，strip 後為空或長度 >50 →422 |
| GET | `/api/meta/pipeline-status` | 各 pipeline job 最近執行狀態 |
| POST | `/api/ai/analyze` | 觸發個股 AI 分析：body `{ticker, mode}`（mode ∈ 近期觀察／中期展望／全面檢視）。建 pending 列＋背景執行，回 202 `{analysis_id}`；ticker 不存在→404，同 ticker+mode 分析進行中→409 |
| GET | `/api/ai/analyses/{id}` | 查單筆分析：status（pending／running／done／failed）、五面向 scores／reasons、summary、total、model；不存在→404 |
| GET | `/api/ai/leaderboard?sort=strong&mode=` | AI 評分榜：每個股取最新一筆 done，依 total 降冪（`strong`，預設）／升冪（`weak`），可選 `mode` 篩選，top 50 |

## LLM 設定（AI 分析）

AI 分析支援三種 provider，經 `AISM_LLM_PROVIDER` 環境變數切換（見 [`.env.example`](.env.example) 的註解）。

**預設為 `mock`——零設定即可跑**：不呼叫任何外部 API、不需 API key，回傳確定性的假分數（依 prompt 內容 hash 派生），reasons 與 summary 皆標明「模擬分析」字樣，供端到端展示與測試。

切換至真實 LLM **無需改動任何程式碼**，只需調整 `.env`：

| provider | 必要環境變數 |
|----------|--------------|
| `mock`（預設） | 無 |
| `anthropic` | `AISM_LLM_PROVIDER=anthropic`、`AISM_LLM_API_KEY=<你的 key>`、`AISM_LLM_MODEL`（如 `claude-sonnet-5`） |
| `openai_compat` | `AISM_LLM_PROVIDER=openai_compat`、`AISM_LLM_BASE_URL=<相容端點>`、`AISM_LLM_API_KEY=<你的 key>`、`AISM_LLM_MODEL=<模型名>` |

改完 `.env` 後重啟後端即生效。缺少必要變數時 factory 會在啟動期以清楚訊息 raise；API key 絕不落入 log 或錯誤訊息。

## 目錄結構

```
AI_Smart_Industry_Map/
├── backend/                # FastAPI 後端
│   ├── app/
│   │   ├── api/            # topics、daily、meta、ai 路由
│   │   ├── llm/            # LLM provider 層（anthropic／openai_compat／mock）
│   │   ├── services/       # analysis（脈絡組裝＋prompt＋run_analysis）
│   │   ├── core/           # 設定（pydantic-settings）
│   │   ├── db/             # SQLAlchemy models、session、seed
│   │   ├── pipeline/       # runner、jobs、scheduler
│   │   │   └── sources/    # TWSE / TPEx / Yahoo / MOPS client
│   │   └── main.py         # app factory
│   └── tests/              # pytest（423 tests）
├── frontend/               # React + Vite 前端
│   └── src/
│       ├── api/            # API client
│       ├── components/     # layout、daily、topics、map 元件
│       ├── pages/          # DailyPage、TopicsPage、TopicDetailPage、TopicMapPage、CompaniesPage、CompanyPage、AiPage
│       └── __tests__/      # vitest（168 tests）
├── data/seeds/             # 題材種子資料（YAML）
├── docs/superpowers/       # 設計 spec 與實作計畫
├── .env.example            # 環境變數範本
└── Makefile                # 開發指令
```

## 技術棧

- **前端**：React 19、Vite 8、TypeScript、Tailwind CSS 4、TanStack Query、React Router、ECharts、Vitest
- **後端**：Python 3.12、FastAPI、SQLAlchemy 2、Pydantic Settings、APScheduler、httpx、curl_cffi（僅 Yahoo 指數：Yahoo 以 TLS 指紋擋非瀏覽器連線，需 Chrome impersonation 才能取得報價）、loguru
- **資料庫**：SQLite
- **工具鏈**：uv（後端）、npm（前端）、Makefile

## 開發狀態

**MVP 完成（切片 1-8 全部完成）。** 全測試通過：**後端 423 tests（pytest）＋前端 168 tests（vitest），共 591 tests。**

### 八切片一覽

| 切片 | 主題 | 交付重點 | 實作計畫 |
|------|------|----------|----------|
| 1＋2 | Foundation | 題材 seed 冪等匯入、TWSE／TPEx 收盤 pipeline（runner + jobs + APScheduler）、`pipeline_runs` 狀態、`/api/topics`＋`/api/meta/pipeline-status`、前端深色 shell 與題材總覽頁 | [plan](docs/superpowers/plans/2026-07-11-slice-1-2-foundation.md) |
| 3 | 題材詳情頁 | `/topic/:slug`＋`/api/topics/{slug}`、ECharts treemap 三週期熱力圖、籌碼訊號、三大法人管線（`institutional_flows`）、`make backfill`、UTC 時間戳序列化 | [plan](docs/superpowers/plans/2026-07-11-slice-3-topic-detail.md) |
| 4 | 產業地圖頁 | `/topic/:slug/map`＋`/api/topics/{slug}/map`、供應鏈上／中／下游分層、公司卡片（角色／關聯度／漲跌／籌碼徽章）、ECharts lazy-load | [plan](docs/superpowers/plans/2026-07-12-slice-4-industry-map.md) |
| 5 | 每日焦點頁 | `/`（首頁）＋`/api/daily`、`/api/daily/announcements`、七檔指數快照（Yahoo）、三大法人金額＋資券餘額、日／週／月強勢股、MOPS 時間軸、新排程（indices／market_stats／mops） | [plan](docs/superpowers/plans/2026-07-12-slice-5-daily-focus.md) |
| 6 | 公司資料庫與個股頁 | `/companies`＋`/api/companies`（搜尋／篩選／分頁）、`/c/:ticker` 詳情＋四張 ECharts 圖表、基本面管線（月營收／本益比／集保）、`make backfill` 擴充 | [plan](docs/superpowers/plans/2026-07-12-slice-6-company-pages.md) |
| 7 | AI 分析 | `/ai`＋三端點 API（202 非同步＋409 防重複／輪詢／排行榜）、LLM provider 抽象層（anthropic／openai_compat／mock，零程式碼切換）、五面向分析 service | [plan](docs/superpowers/plans/2026-07-12-slice-7-ai-analysis.md) |
| 8 | 全站搜尋與打磨 | `/api/search`（⌘K 命令面板後端）、前端 CommandPalette（跨公司／題材檢索、鍵盤導航）、NavBar 產業地圖動態入口、全站打磨 | [plan](docs/superpowers/plans/2026-07-12-slice-8-search-polish.md) |

設計 spec：[`docs/superpowers/specs/2026-07-11-ai-stock-map-clone-design.md`](docs/superpowers/specs/2026-07-11-ai-stock-map-clone-design.md)

## 已知限制

- **Safari `<summary>` flex 佈局未驗證**：可展開區塊（`<details>`／`<summary>`）的 flex 佈局僅於 Chromium／Firefox 驗證，Safari 下的呈現未實測。
- **單行程背景任務**：AI 分析採單行程背景執行（`run_analysis`），後端重啟時進行中的 `pending`／`running` 分析不會續跑，需重新觸發。
- **LLM 預設為 mock**：預設 provider 回傳確定性假分數（標明「模擬分析」），零設定即可端到端展示；切換至真實 LLM 見上方「LLM 設定」段。
- **排行／搜尋 universe＝已收錄公司**：AI 排行榜與全站搜尋的範圍僅涵蓋已入庫（隨題材 seed 收錄）的公司，非全市場；universe 隨題材擴充而成長。
- **未做原站像素級比對**：參考站部分頁面在登入牆之後，故未進行像素級對照，UI 以功能對等為準。

## 後續 roadmap

- **登入／會員／金流**：第一階段明確排除項，MVP 不含帳號體系與付費機制。
- **更多題材 seed**：擴充題材與成分股 seed，帶動搜尋／排行 universe 成長。
- **全市場 universe**：由「已收錄公司」擴展至全市場個股。
- **原站截圖比對打磨**：取得登入後畫面後，進行像素級對照與 UI 打磨。
