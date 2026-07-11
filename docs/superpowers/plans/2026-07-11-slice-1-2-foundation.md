# 切片 1＋2：專案骨架與第一條端到端路徑 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立前後端骨架、DB schema、矽光子題材 seed，並打通「TWSE/TPEx 收盤資料 → SQLite → REST API → 題材總覽頁」的第一條完整路徑。

**Architecture:** 方案 A——React (Vite) 前端＋FastAPI 單一後端行程（APScheduler 內嵌）＋SQLite。編輯內容以 YAML seeds 為真理來源，pipeline job 狀態寫入 `pipeline_runs` 供 UI 顯示「資料更新於」。

**Tech Stack:** Python 3.12＋uv｜FastAPI｜SQLAlchemy 2｜APScheduler｜httpx｜React 19＋Vite＋TypeScript｜Tailwind v4｜TanStack Query｜pytest｜vitest

**Spec:** `docs/superpowers/specs/2026-07-11-ai-stock-map-clone-design.md`（含決策紀錄與附錄 A seed 資料）

**執行模式（使用者指定）：** 每個 task 派 **Opus 4.8** subagent 實作，另派 **Opus 4.8** fresh-context reviewer；同一 task 連續失敗 2 次 → 停止，帶完整失敗軌跡回報主對話（Fable 5）裁決。實作前先開分支 `feat/foundation`。

---

## File Structure（本計畫落地後）

```
├── Makefile                       # dev / seed / fetch / test 入口
├── .gitignore / .env.example / README.md
├── backend/
│   ├── pyproject.toml             # uv 管理
│   ├── app/
│   │   ├── main.py                # app factory＋lifespan（scheduler、CORS）
│   │   ├── core/config.py         # pydantic-settings（DB 路徑、CORS origin）
│   │   ├── db/base.py             # engine、SessionLocal、WAL pragma
│   │   ├── db/models.py           # companies/topics/topic_companies/quotes_daily/pipeline_runs
│   │   ├── db/seed.py             # YAML → DB 冪等 upsert
│   │   ├── pipeline/sources/twse.py    # 上市收盤 OpenAPI client＋parser
│   │   ├── pipeline/sources/tpex.py    # 上櫃收盤 OpenAPI client＋parser
│   │   ├── pipeline/runner.py     # run_job()：重試、pipeline_runs 記錄
│   │   ├── pipeline/jobs.py       # fetch_tw_quotes
│   │   ├── pipeline/scheduler.py  # APScheduler 註冊（平日 14:05）
│   │   ├── api/topics.py          # GET /api/topics（卡片＋漲幅排行）
│   │   └── api/meta.py            # GET /api/meta/pipeline-status
│   ├── cli.py                     # python -m backend.cli seed|fetch
│   └── tests/
│       ├── conftest.py            # tmp SQLite fixture、TestClient
│       ├── fixtures/twse_stock_day_all.json / tpex_daily_close.json
│       ├── test_seed.py / test_sources.py / test_runner.py
│       ├── test_jobs.py / test_api_topics.py / test_api_meta.py
├── data/seeds/silicon-photonics.yaml
└── frontend/
    ├── package.json / vite.config.ts / tsconfig.json
    └── src/
        ├── main.tsx / App.tsx      # Router＋QueryClientProvider＋深色 shell
        ├── components/layout/NavBar.tsx
        ├── api/client.ts / api/topics.ts   # fetch 封裝＋型別
        ├── pages/TopicsPage.tsx
        ├── components/topics/TopicCard.tsx / RankFocusCards.tsx
        └── __tests__/TopicCard.test.tsx
```

**檔案責任邊界：** sources 只管「抓＋解析成中立 dict」；jobs 只管「dict → DB upsert」；runner 只管「執行紀錄與重試」；API 只讀 DB。前端 api/ 層集中型別與 fetch，元件不直接打網路。

---

### Task 0: 分支與 repo 基礎

**Files:** Create: `.gitignore`, `.env.example`, `README.md`, `Makefile`

- [ ] **Step 1:** `git checkout -b feat/foundation`
- [ ] **Step 2:** 建立 `.gitignore`（Python: `.venv/ __pycache__/ *.db data/raw/`；Node: `node_modules/ dist/`；`.env`）
- [ ] **Step 3:** 建立 `.env.example`：

```env
# backend
AISM_DB_PATH=./data/aism.db
AISM_CORS_ORIGINS=http://localhost:5173
```

- [ ] **Step 4:** `README.md` 寫最小啟動說明（後續 task 補充）；`Makefile` 先放 `help` target
- [ ] **Step 5:** Commit：`chore: repo 基礎（gitignore/env.example/Makefile）`

---

### Task 1: 後端腳手架＋healthz

**Files:** Create: `backend/pyproject.toml`, `backend/app/main.py`, `backend/app/core/config.py`, `backend/tests/conftest.py`, `backend/tests/test_healthz.py`

- [ ] **Step 1:** `cd backend && uv init --no-workspace && uv add fastapi "uvicorn[standard]" sqlalchemy pydantic-settings httpx apscheduler pyyaml loguru && uv add --dev pytest httpx`，並在 `pyproject.toml` 加：

```toml
[tool.pytest.ini_options]
pythonpath = ["."]
```

（沒有這段，`tests/` 下 `from app.main import ...` 會因 sys.path 不含 `backend/` 而一直 ModuleNotFoundError，跟 TDD 的「預期失敗」混在一起）
- [ ] **Step 2:** 寫失敗測試 `backend/tests/test_healthz.py`：

```python
from fastapi.testclient import TestClient
from app.main import create_app

def test_healthz():
    client = TestClient(create_app())
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
```

- [ ] **Step 3:** `uv run pytest tests/test_healthz.py -v` → 預期 FAIL（`ModuleNotFoundError: app`）
- [ ] **Step 4:** 實作 `app/core/config.py`（`Settings(BaseSettings)`：`db_path: str = "./data/aism.db"`、`cors_origins: list[str]`，env prefix `AISM_`）與 `app/main.py`：

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings

def create_app() -> FastAPI:
    app = FastAPI(title="AI Smart Industry Map")
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
                       allow_methods=["*"], allow_headers=["*"])
    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}
    return app
```

- [ ] **Step 5:** `uv run pytest -v` → PASS；Commit：`feat: FastAPI 腳手架與 healthz`

---

### Task 2: DB models＋session

**Files:** Create: `backend/app/db/base.py`, `backend/app/db/models.py`, `backend/tests/test_models.py`

- [ ] **Step 1:** 失敗測試（tmp SQLite 建表＋WAL＋roundtrip）：

```python
from app.db.base import make_engine, Base
from app.db import models
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

def test_create_all_and_wal(tmp_path):
    eng = make_engine(f"{tmp_path}/t.db")
    Base.metadata.create_all(eng)
    names = set(inspect(eng).get_table_names())
    assert {"companies", "topics", "topic_companies", "quotes_daily", "pipeline_runs"} <= names
    with eng.connect() as c:
        assert c.execute(text("PRAGMA journal_mode")).scalar() == "wal"

def test_quote_roundtrip(tmp_path):
    eng = make_engine(f"{tmp_path}/t.db"); Base.metadata.create_all(eng)
    with Session(eng) as s:
        s.add(models.Company(ticker="2330", name="台積電", market="TW"))
        s.add(models.QuoteDaily(ticker="2330", date="2026-07-11", open=1080, high=1095,
                                low=1075, close=1090, volume=33169039, change_pct=1.40))
        s.commit()
        assert s.get(models.QuoteDaily, ("2330", "2026-07-11")).close == 1090
```

- [ ] **Step 2:** 跑測試 → FAIL
- [ ] **Step 3:** 實作。models 欄位（皆含 `created_at/updated_at` 由 mixin 提供）：
  - `Company`: ticker(PK str)、name、market(`TW|US|JP`)、industry_tags(JSON)、has_futures(bool, default False)
  - `Topic`: slug(PK)、title、description(Text)、market_tab(`tw|us|jp|chain|etf`)、metrics(JSON)、verified_at(str date)
  - `TopicCompany`: topic_slug＋ticker＋category(複合 PK)、chain_level(`上游|中游|下游`)、category_desc、role(`龍頭|利基|新興|挑戰`)、relevance(`高|中|低`)、FK 到 topics/companies
  - `QuoteDaily`: ticker＋date(複合 PK)、open/high/low/close(float, nullable)、volume(int)、change_pct(float, nullable)
  - `PipelineRun`: id(auto)、job_name、started_at/finished_at(datetime)、status(`success|failed|running`)、error(Text nullable)
  - `make_engine(path)`：`create_engine(f"sqlite:///{path}")`＋connect event 設 `PRAGMA journal_mode=WAL`
- [ ] **Step 4:** 跑測試 → PASS
- [ ] **Step 5:** Commit：`feat: DB models（5 張核心表）與 WAL engine`

---

### Task 3: 矽光子 seed YAML＋冪等匯入

**Files:** Create: `data/seeds/silicon-photonics.yaml`, `backend/app/db/seed.py`, `backend/tests/test_seed.py`；Modify: `backend/cli.py`(new), `Makefile`

- [ ] **Step 1:** 建 `data/seeds/silicon-photonics.yaml`。結構如下；公司組成、角色、關聯度**照 spec 附錄 A**（17 檔）；`description` 與 `category desc` 用自行改寫的文字（**禁止**貼上原站文案）：

```yaml
slug: silicon-photonics
title: 光通訊｜矽光子與 CPO
market_tab: tw
description: >-
  （改寫版描述：以 CPO 共同封裝解決 AI 資料中心傳輸功耗與頻寬瓶頸的
  半導體異質整合技術，台積電 COUPE 平台為生態核心⋯⋯由實作者依 spec
  附錄 A 的事實要點重新撰寫 2-3 句）
verified_at: "2026-07-11"
metrics:
  cagr: "45%+"
  market_size: "10.2 (USD B)"
  tech_core: CPO 共同封裝
  main_spec: 1.6T 導入 / 3.2T 驗證
  commercial_node: 2026 大規模量產
  barrier: 台積電生態系 / 高度客製化
companies:            # 公司主檔（17 檔，market 皆 TW）
  - {ticker: "2330", name: 台積電, has_futures: true}
  - {ticker: "3443", name: 創意, has_futures: true}
  # ⋯⋯其餘 15 檔（3081/3450/4979/2426/6442/3163/2489/3711/4977/6789/3363/6223/6515/3289/6451）
chain:
  - level: 上游
    categories:
      - name: 矽光子製程代工平台
        desc: （改寫）
        companies:
          - {ticker: "2330", role: 龍頭, relevance: 高}
          - {ticker: "3443", role: 龍頭, relevance: 中}
      - name: 外部光源與雷射引擎
        companies: [{ticker: "3081", role: 龍頭, relevance: 高}, {ticker: "3450", role: 利基, relevance: 高},
                    {ticker: "4979", role: 利基, relevance: 高}, {ticker: "2426", role: 利基, relevance: 中}]
      - name: 高密度光纖套件與被動元件
        companies: [{ticker: "6442", role: 龍頭, relevance: 高}, {ticker: "3163", role: 利基, relevance: 高},
                    {ticker: "2489", role: 新興, relevance: 低}]
  - level: 中游
    categories:
      - name: CPO 共同封裝與異質整合
        companies: [{ticker: "3711", role: 龍頭, relevance: 高}, {ticker: "4977", role: 挑戰, relevance: 高},
                    {ticker: "6789", role: 挑戰, relevance: 中}, {ticker: "3363", role: 利基, relevance: 高},
                    {ticker: "3450", role: 利基, relevance: 高}, {ticker: "6451", role: 利基, relevance: 中}]
      - name: 高密度光纖陣列 (FAU)
        companies: [{ticker: "3363", role: 利基, relevance: 高}]
      - name: 矽光子測試介面與檢測
        companies: [{ticker: "3711", role: 龍頭, relevance: 高}, {ticker: "6223", role: 龍頭, relevance: 高},
                    {ticker: "6515", role: 利基, relevance: 高}, {ticker: "3289", role: 利基, relevance: 中}]
  - level: 下游
    categories:
      - {name: CPO 整合交換器系統, placeholder: true}
      - {name: AI 算力單元與高效能運算, placeholder: true}
```

- [ ] **Step 2:** 失敗測試 `test_seed.py`：`load_seeds(dir, session)` 後 topics=1、companies=17、topic_companies 筆數正確；**再跑一次不重複**（冪等）；改 YAML title 後重跑會更新。
- [ ] **Step 3:** 跑測試 → FAIL
- [ ] **Step 4:** 實作 `app/db/seed.py`（pyyaml 讀檔 → merge/upsert；placeholder 分類也入庫，無公司）與 `backend/cli.py`：

```python
# cli.py
import sys
from app.core.config import settings
from app.db.base import make_engine, Base
from app.db.seed import load_seeds
from sqlalchemy.orm import Session

def main():
    cmd = sys.argv[1]
    eng = make_engine(settings.db_path); Base.metadata.create_all(eng)
    if cmd == "seed":
        with Session(eng) as s:
            load_seeds("../data/seeds", s); s.commit()
    elif cmd == "fetch":          # Task 6 補上
        from app.pipeline.jobs import fetch_tw_quotes
        from app.pipeline.runner import run_job
        run_job(eng, "fetch_tw_quotes", fetch_tw_quotes)
```

- [ ] **Step 5:** 測試 PASS；`Makefile` 加 `seed:`＝`cd backend && uv run python -m cli seed`；Commit：`feat: 矽光子 seed 與冪等匯入`

---

### Task 4: TWSE／TPEx source clients

**Files:** Create: `backend/app/pipeline/sources/twse.py`, `.../tpex.py`, `backend/tests/fixtures/*.json`, `backend/tests/test_sources.py`, `backend/scripts/record_fixtures.py`

- [ ] **Step 1:** 先寫 `scripts/record_fixtures.py`：實際 GET 下列端點、把回應前 5 筆存進 fixtures（**執行一次並人工檢視欄位名**，若與本計畫假設不符，以真實回應為準調整 parser 與後續步驟）：
  - 上市：`https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL`
  - 上櫃：`https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes`
- [ ] **Step 2:** 失敗測試 `test_sources.py`（用 fixtures，不打網路）：

```python
def test_parse_twse(twse_fixture):
    rows = twse.parse(twse_fixture)
    r = next(x for x in rows if x["ticker"] == "2330")
    assert set(r) == {"ticker","name","open","high","low","close","volume","change_pct"}
    assert r["close"] > 0 and abs(r["change_pct"]) < 30

def test_parse_handles_dash_prices(twse_fixture_with_dash):  # 停牌股 "--"
    rows = twse.parse(twse_fixture_with_dash)
    assert rows[0]["close"] is None
```

- [ ] **Step 3:** 跑測試 → FAIL
- [ ] **Step 4:** 實作兩個 module：`fetch() -> list[dict]`（httpx，timeout 30s）＋`parse(raw) -> list[dict]`。重點：數字欄去逗號、`"--"`→None、`change_pct = change / (close - change) * 100`（除零與 None 防護）、TPEx ROC 日期轉西元。**不做**其他清洗（YAGNI）。
- [ ] **Step 5:** 測試 PASS；Commit：`feat: TWSE/TPEx 收盤資料 source clients`

---

### Task 5: pipeline runner（執行紀錄＋重試）

**Files:** Create: `backend/app/pipeline/runner.py`, `backend/tests/test_runner.py`

- [ ] **Step 1:** 失敗測試：成功 job 寫入 `success` 紀錄；raise 的 job 重試 3 次（backoff 可注入為 0）後寫 `failed`＋error 訊息；重試中第 2 次成功則 `success`。
- [ ] **Step 2:** 跑測試 → FAIL
- [ ] **Step 3:** 實作 `run_job(engine, name, fn, retries=3, backoff=(1,4,16))`：開 `PipelineRun(status="running")` → 執行 `fn(session)` → 更新狀態；例外時 sleep backoff 重試；loguru 記錄。
- [ ] **Step 4:** 測試 PASS
- [ ] **Step 5:** Commit：`feat: pipeline runner 與執行紀錄`

---

### Task 6: fetch_tw_quotes job

**Files:** Create: `backend/app/pipeline/jobs.py`, `backend/tests/test_jobs.py`；Modify: `backend/cli.py`, `Makefile`

- [ ] **Step 1:** 失敗測試（monkeypatch 兩個 source 的 `fetch` 回 fixtures）：執行後 `quotes_daily` 有今日 2330 與上櫃股資料；**只 upsert seed 內已知 companies 的代號**（其餘略過）；重跑同日不重複。
- [ ] **Step 2:** 跑測試 → FAIL
- [ ] **Step 3:** 實作 `fetch_tw_quotes(session)`：兩來源 fetch＋parse → 過濾出 companies 表已有的 ticker → upsert `quotes_daily`。date 欄位：**優先用來源回應自帶的資料日期**（Task 4 錄 fixtures 時確認欄位）；來源無日期才 fallback 台北今日，並註記此假設（假日/盤前執行會標錯日期，MVP 可接受）。
- [ ] **Step 4:** 測試 PASS；`make fetch` 接上 cli
- [ ] **Step 5:** Commit：`feat: fetch_tw_quotes 收盤資料 job`

---

### Task 7: APScheduler 掛載

**Files:** Create: `backend/app/pipeline/scheduler.py`；Modify: `backend/app/main.py`

- [ ] **Step 1:** 失敗測試：`create_app()` 後 scheduler 存在且含 `fetch_tw_quotes` job（cron：平日 14:05 Asia/Taipei）；testing 模式（env `AISM_SCHEDULER_ENABLED=false`）不啟動。
- [ ] **Step 2:** 跑測試 → FAIL
- [ ] **Step 3:** 實作 `scheduler.py`（BackgroundScheduler＋CronTrigger）＋`main.py` lifespan 啟停；預設 enabled，conftest 設 env 關閉。
- [ ] **Step 4:** 測試 PASS
- [ ] **Step 5:** Commit：`feat: APScheduler 排程掛載`

---

### Task 8: topics API＋pipeline-status API

**Files:** Create: `backend/app/api/topics.py`, `backend/app/api/meta.py`, `backend/tests/test_api_topics.py`, `backend/tests/test_api_meta.py`；Modify: `backend/app/main.py`

- [ ] **Step 1:** 失敗測試（conftest 提供 seeded＋假 quotes 的 TestClient）：
  - `GET /api/topics?market=tw` → `{topics: [{slug,title,description,market_tab,company_count,verified_at,change_pct_avg}], rank: [前三名 {slug,title,company_count,change_pct_avg}]}`；`market=etf` → 空陣列
  - **`company_count` 與 `change_pct_avg` 一律以 DISTINCT ticker 計算**（topic_companies 有跨分類重複：3711/3363/3450 各出現兩次，列數 20 但成員僅 17 檔）；測試必須斷言矽光子 `company_count == 17`
  - `GET /api/meta/pipeline-status` → `[{job_name,last_success_at,last_status}]`
  - 錯誤路徑：`GET /api/topics?market=xx` → 422
- [ ] **Step 2:** 跑測試 → FAIL
- [ ] **Step 3:** 實作：Pydantic response models；`change_pct_avg`＝該題材成員（distinct ticker）最新日 change_pct 平均（SQL 一次查詢，NULL 略過）；rank＝**依 avg 降冪取 3**（漲），參數 `direction=down` 時取跌幅前 3
- [ ] **Step 4:** 測試 PASS
- [ ] **Step 5:** Commit：`feat: topics 與 pipeline-status API`

---

### Task 9: 前端腳手架（深色 shell）

**Files:** Create: `frontend/`（Vite react-ts template）、`src/App.tsx`、`src/components/layout/NavBar.tsx`、`src/api/client.ts`、`vitest 設定`、`src/__tests__/smoke.test.tsx`；Modify: `Makefile`, `.env.example`(前端 `VITE_API_BASE`)

- [ ] **Step 1:** `npm create vite@latest frontend -- --template react-ts && cd frontend && npm i && npm i @tanstack/react-query react-router-dom && npm i -D tailwindcss @tailwindcss/vite vitest @testing-library/react @testing-library/jest-dom jsdom`
- [ ] **Step 2:** Tailwind v4 接入（vite plugin＋`@import "tailwindcss"`）；`index.css` 定深色 palette CSS vars（背景 `#0b1220` 系、卡片 `#111a2e` 系、主色 indigo）；`html` 固定 dark
- [ ] **Step 3:** `App.tsx`：QueryClientProvider＋BrowserRouter＋NavBar（每日焦點/題材總覽/產業地圖/公司資料庫/AI 分析——未實作路由先 disabled 樣式）＋`<Routes>`（`/topics` → TopicsPage 佔位）
- [ ] **Step 4:** 失敗 smoke test：render App、`getByText("題材總覽")`；跑 `npx vitest run` → FAIL → 補實作 → PASS
- [ ] **Step 5:** `make dev`（concurrently 跑 `uvicorn --reload`＋`vite`）；Commit：`feat: 前端腳手架與深色 shell`

---

### Task 10: 題材總覽頁 UI

**Files:** Create: `src/pages/TopicsPage.tsx`, `src/components/topics/TopicCard.tsx`, `src/components/topics/RankFocusCards.tsx`, `src/api/topics.ts`, `src/__tests__/TopicCard.test.tsx`

- [ ] **Step 1:** `api/topics.ts`：型別 `TopicSummary`／`TopicsResponse`＋`useTopics(market)` hook（TanStack Query，30s refetch）
- [ ] **Step 2:** 失敗元件測試：TopicCard 顯示 title、`N 家公司` 徽章、核實日期、漲跌色（`change_pct_avg>0` 紅、`<0` 綠——台股慣例紅漲綠跌）
- [ ] **Step 3:** 跑 vitest → FAIL
- [ ] **Step 4:** 實作三個元件：RankFocusCards（#1-#3 大卡，漲/跌 toggle）、TopicCard（icon＋徽章＋描述截兩行＋「探索產業地圖」按鈕 disabled）、TopicsPage（市場五分頁 tabs → useTopics）；空資料顯示佔位
- [ ] **Step 5:** vitest PASS；Commit：`feat: 題材總覽頁`

---

### Task 11: 端到端驗證＋文件

**Files:** Modify: `README.md`

- [ ] **Step 1:** 全新環境驗證：`make seed && make fetch && make dev`
- [ ] **Step 2:** 瀏覽 `http://localhost:5173/topics`：看到矽光子題材卡（17 家公司、真實今日漲跌均值）與排行卡；`/api/meta/pipeline-status` 顯示 fetch 成功時間
- [ ] **Step 3:** 全部測試：`cd backend && uv run pytest` 與 `cd frontend && npx vitest run` → 全 PASS
- [ ] **Step 4:** README 補齊：架構圖、指令、env 說明
- [ ] **Step 5:** Commit：`docs: README 啟動與架構說明`

---

## 驗收條件（整份計畫）

1. `make seed && make fetch && make dev` 三指令冷啟動成功
2. `/topics` 頁顯示矽光子題材與真實 TWSE/TPEx 當日資料
3. 後端 pytest 全綠、前端 vitest 全綠（宣稱通過前必須實跑並附輸出）
4. 無 console.log/print 殘留、無硬編碼秘密、檔案 ≤400 行

## 注意事項（給實作 subagent）

- **fixtures 先於 parser**：Task 4 必須先錄真實回應再寫 parser，欄位名以真實回應為準
- spec §4 的「原始回應落地 `data/raw/` 保留 7 天」**刻意延後**至後續切片，本計畫不做（.gitignore 已預留目錄）
- 原站文案**禁止逐字複製**，seed 描述一律改寫
- 測試失敗 → 修實作不修測試（測試本身寫錯要說明）
- 每個 task 結束都 commit（atomic，訊息含 type prefix）
