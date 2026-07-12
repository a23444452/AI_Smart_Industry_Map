# AI 智慧產業地圖

以投資題材為軸，串接台股產業鏈、公司清單與每日收盤漲跌，一頁看懂 AI 時代的關鍵產業脈絡。

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
- **API**（FastAPI）讀 SQLite，對前端提供題材、每日焦點與 pipeline 狀態 JSON。
- **frontend**（React + Vite）呼叫 API，渲染每日焦點頁與題材總覽頁。

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

啟動後開啟 <http://localhost:5173/> 檢視每日焦點，<http://localhost:5173/topics> 檢視題材總覽，<http://localhost:5173/companies> 檢視公司資料庫。

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
| GET | `/api/meta/pipeline-status` | 各 pipeline job 最近執行狀態 |

## 目錄結構

```
AI_Smart_Industry_Map/
├── backend/                # FastAPI 後端
│   ├── app/
│   │   ├── api/            # topics、daily、meta 路由
│   │   ├── core/           # 設定（pydantic-settings）
│   │   ├── db/             # SQLAlchemy models、session、seed
│   │   ├── pipeline/       # runner、jobs、scheduler
│   │   │   └── sources/    # TWSE / TPEx / Yahoo / MOPS client
│   │   └── main.py         # app factory
│   └── tests/              # pytest（326 tests）
├── frontend/               # React + Vite 前端
│   └── src/
│       ├── api/            # API client
│       ├── components/     # layout、daily、topics、map 元件
│       ├── pages/          # DailyPage、TopicsPage、TopicDetailPage、TopicMapPage、CompaniesPage、CompanyPage
│       └── __tests__/      # vitest（127 tests）
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

切片 1-6 已完成，後端 326 tests、前端 127 tests 全數通過。已實作功能：

切片 1＋2（foundation）：

- 題材種子匯入（矽光子｜矽光子與 CPO，17 檔成分股），冪等 upsert
- TWSE／TPEx 台股收盤抓取 pipeline（runner + jobs），APScheduler 定時排程
- pipeline 執行狀態記錄（`pipeline_runs`）
- 題材與 pipeline 狀態 API（`/api/topics`、`/api/meta/pipeline-status`）
- 前端深色 shell 與題材總覽頁（題材卡片、排行 focus cards、漲跌顯示）

切片 3（題材總覽頁）：

- 主題總覽頁（`/topic/:slug`，由題材卡片標題連入）與 `/api/topics/{slug}` API
- treemap 熱力圖（ECharts，日／週／月三週期成分股漲跌）
- 籌碼訊號（chip_signals，近 5 日外資／投信／三大法人買超家數）
- 三大法人買賣超管線（`institutional_flows` 表、fetch_institutional job，16:10／17:10 cron）
- 歷史行情回填 CLI（`make backfill`：近 2-3 月行情＋近 14 日法人）
- API 時間戳 UTC 序列化（Z 尾碼）與前端「資料更新於」顯示

切片 4（產業地圖頁）：

- 產業地圖頁（`/topic/:slug/map`）與 `/api/topics/{slug}/map` API
- 供應鏈分層檢視（上游／中游／下游），各層依分類分組
- 公司卡片：角色標籤（龍頭／要角）、關聯度、收盤漲跌、籌碼徽章（有股票期貨／投信買超等）
- 下游未布局分類以 placeholder 呈現
- ECharts 改採 lazy-load（動態 import），與題材色彩同源

切片 5（每日焦點頁）：

- 每日焦點頁（`/`，設為首頁）與 `/api/daily`、`/api/daily/announcements` API
- 指數行情列：加權／費半／S&P 500／TSM／NVDA／日經／VIX 七檔快照（Yahoo 延遲報價）
- 三大法人買賣金額（TWSE BFI82U）與資券餘額（信用交易統計）最新日資料
- 強勢股排行（日／週／月三 tab，依漲跌幅排序）
- MOPS 重大訊息時間軸（依日期切換，台北時區歸日）
- 新排程：`fetch_indices` 平日 08–22 時每 15 分鐘、`fetch_market_stats` 平日三發（16:20／17:20／21:45，冪等補抓晚出資料）、`fetch_mops` 每日 19:10（含假日）
- `make backfill` 擴充市場統計回填（法人金額＋資券餘額，近 30 日）

切片 6（公司資料庫與個股頁）：

- 公司資料庫頁（`/companies`）與 `/api/companies` API：代號／名稱搜尋（debounce 300ms）、題材篩選、分頁
- 個股頁（`/c/:ticker`）與 `/api/companies/{ticker}` 詳情、`/api/companies/{ticker}/charts/{kind}` 圖表 API
- 個股四張圖表：K 線（≥100 交易日）、本益比河流圖、三大法人買賣超、集保大戶持股比（ECharts，lazy-load）
- 基本面資料管線：月營收（fetch_fundamentals 每日 09:00）、當日本益比／殖利率（fetch_per 平日 15:00）、集保股權分散（fetch_tdcc 週六 09:30）
- `make backfill` 擴充：歷史行情回填至近 6 個月（每檔 ≥100 交易日）、本益比歷史回填（近 3 個月）

設計文件：

- 設計 spec：[`docs/superpowers/specs/2026-07-11-ai-stock-map-clone-design.md`](docs/superpowers/specs/2026-07-11-ai-stock-map-clone-design.md)
- 實作計畫（切片 1＋2）：[`docs/superpowers/plans/2026-07-11-slice-1-2-foundation.md`](docs/superpowers/plans/2026-07-11-slice-1-2-foundation.md)
- 實作計畫（切片 3）：[`docs/superpowers/plans/2026-07-11-slice-3-topic-detail.md`](docs/superpowers/plans/2026-07-11-slice-3-topic-detail.md)
- 實作計畫（切片 4）：[`docs/superpowers/plans/2026-07-12-slice-4-industry-map.md`](docs/superpowers/plans/2026-07-12-slice-4-industry-map.md)
- 實作計畫（切片 5）：[`docs/superpowers/plans/2026-07-12-slice-5-daily-focus.md`](docs/superpowers/plans/2026-07-12-slice-5-daily-focus.md)
- 實作計畫（切片 6）：[`docs/superpowers/plans/2026-07-12-slice-6-company-pages.md`](docs/superpowers/plans/2026-07-12-slice-6-company-pages.md)
