# AI 智慧產業地圖

以投資題材為軸，串接台股產業鏈、公司清單與每日收盤漲跌，一頁看懂 AI 時代的關鍵產業脈絡。

## 架構

```
                         ┌──────────────────────┐
   TWSE / TPEx  ───────▶ │   pipeline（抓取）    │
   （台股收盤 API）        │  runner + jobs +     │
                         │  APScheduler 排程     │
                         └──────────┬───────────┘
                                    │ upsert
                                    ▼
   ┌────────────┐   HTTP    ┌──────────────┐   ORM    ┌──────────────┐
   │  frontend  │ ───────▶  │     API      │ ───────▶ │    SQLite    │
   │ React+Vite │ ◀───────  │   FastAPI    │ ◀─────── │   aism.db    │
   └────────────┘   JSON    └──────────────┘  query   └──────────────┘
   :5173                     :8000
```

- **pipeline** 從 TWSE／TPEx 抓取台股收盤，經 runner 冪等 upsert 進 SQLite；APScheduler 定時排程。
- **API**（FastAPI）讀 SQLite，對前端提供題材與 pipeline 狀態 JSON。
- **frontend**（React + Vite）呼叫 API，渲染題材總覽頁。

## 快速開始

需求：Python 3.12+、[uv](https://docs.astral.sh/uv/)、Node.js 20+。

```bash
cp .env.example .env       # 建立環境變數
make seed                  # 匯入題材 seeds（矽光子）
make fetch                 # 抓取台股收盤資料
make backfill              # 回填歷史行情（2-3 月）與三大法人（近 14 日）
make dev                   # 同時啟動後端(:8000) 與前端(:5173)
```

啟動後開啟 <http://localhost:5173/topics> 檢視題材總覽。

## 指令表（`make help`）

| 指令 | 說明 |
|------|------|
| `make help` | 顯示可用指令清單 |
| `make seed` | 匯入題材 seeds（`data/seeds/*.yaml` → SQLite） |
| `make fetch` | 抓取台股收盤資料並寫入 DB |
| `make backfill` | 回填歷史行情（近 2-3 月）與三大法人買賣超（近 14 日） |
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
| GET | `/api/meta/pipeline-status` | 各 pipeline job 最近執行狀態 |

## 目錄結構

```
AI_Smart_Industry_Map/
├── backend/                # FastAPI 後端
│   ├── app/
│   │   ├── api/            # topics、meta 路由
│   │   ├── core/           # 設定（pydantic-settings）
│   │   ├── db/             # SQLAlchemy models、session、seed
│   │   ├── pipeline/       # runner、jobs、scheduler
│   │   │   └── sources/    # TWSE / TPEx client
│   │   └── main.py         # app factory
│   └── tests/              # pytest（111 tests）
├── frontend/               # React + Vite 前端
│   └── src/
│       ├── api/            # API client
│       ├── components/     # layout、topics 元件
│       ├── pages/          # TopicsPage、TopicDetailPage
│       └── __tests__/      # vitest（43 tests）
├── data/seeds/             # 題材種子資料（YAML）
├── docs/superpowers/       # 設計 spec 與實作計畫
├── .env.example            # 環境變數範本
└── Makefile                # 開發指令
```

## 技術棧

- **前端**：React 19、Vite 8、TypeScript、Tailwind CSS 4、TanStack Query、React Router、ECharts、Vitest
- **後端**：Python 3.12、FastAPI、SQLAlchemy 2、Pydantic Settings、APScheduler、httpx、loguru
- **資料庫**：SQLite
- **工具鏈**：uv（後端）、npm（前端）、Makefile

## 開發狀態

切片 1＋2＋3 已完成，後端 111 tests、前端 43 tests 全數通過。已實作功能：

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

設計文件：

- 設計 spec：[`docs/superpowers/specs/2026-07-11-ai-stock-map-clone-design.md`](docs/superpowers/specs/2026-07-11-ai-stock-map-clone-design.md)
- 實作計畫（切片 1＋2）：[`docs/superpowers/plans/2026-07-11-slice-1-2-foundation.md`](docs/superpowers/plans/2026-07-11-slice-1-2-foundation.md)
- 實作計畫（切片 3）：[`docs/superpowers/plans/2026-07-11-slice-3-topic-detail.md`](docs/superpowers/plans/2026-07-11-slice-3-topic-detail.md)
