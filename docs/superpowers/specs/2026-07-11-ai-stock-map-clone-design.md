# AI 智慧產業地圖 Clone — 設計文件

- **日期**：2026-07-11
- **狀態**：已核可（使用者確認方案 A）
- **參考網站**：https://aistockmap.com （v4.9.0，功能結構參考）
- **分工約定**：規劃/設計/卡關救援 = Fable 5（主對話）；實作與 code review = Opus 4.8 subagents（實作者與 reviewer 分離、fresh context）；同一子任務連續失敗 2 次 → 帶完整失敗軌跡升回 Fable 5。

## 1. 目標與範圍

打造一個功能對齊 aistockmap.com 的台/美/日股產業鏈分析平台 MVP，使用真實免費市場資料。

### MVP 範圍（第一階段）

| 模組 | 內容 |
|------|------|
| 題材總覽 | 今日產業漲幅焦點排行、題材卡片格（台股/美股/日股/產業鏈/ETF 分頁） |
| 主題總覽頁 | 產業描述、關鍵指標、產業漲跌 treemap 熱力圖（單日/單週/單月）、籌碼訊號 |
| 產業地圖 | 供應鏈上/中/下游分層 → 分類 → 公司卡片（角色標籤、關聯度、徽章） |
| 每日焦點 | 指數行情、三大法人、資券變化、本週強勢股、MOPS 重大訊息 |
| 公司資料庫＋個股頁 | 搜尋/篩選、報價、K 線、本益比河流圖、法人買賣超、大戶持股比例 |
| AI 分析 | 五面向評分（題材/基本/技術/籌碼/新聞）、三種模式、排行榜 |
| 橫向功能 | ⌘K 全站搜尋、深色主題、各區塊「資料更新於」狀態 |

### 明確不做（第一階段）

- 登入 / 會員訂閱 / 金流 / Premium 內容鎖（架構預留權限層，API 回應保留 `is_premium` 欄位但一律開放）
- AI 分析每日配額（DB 保留欄位，不強制）
- 財經創作者模組、Podcast 解析、產業新聞編輯內容
- 主動式 ETF 持股追蹤（無穩定免費來源，列為後續研究）
- 市場熱力圖獨立頁（主題頁內的 treemap 已涵蓋核心體驗）
- 新手導覽、版本公告 modal、PWA

### 決策紀錄

| 決策點 | 選擇 |
|--------|------|
| 資料來源 | 真實免費 API：TWSE OpenAPI、FinMind、yfinance、MOPS、TDCC 開放資料 |
| 技術棧 | 前後端分離：React 19 (Vite, TS, Tailwind v4) ＋ Python FastAPI (uv) |
| 架構 | 方案 A：單一後端行程，APScheduler 內嵌，SQLite |
| LLM | Provider 抽象：Anthropic 原生 API 與 OpenAI 相容介面（env 切換） |
| 部署 | 本機開發優先，架構保持可攜（之後換 Postgres＋獨立 worker 即可上雲） |
| 編輯內容 | 分類結構與事實資料照原站建置；描述性文案一律改寫（著作權） |

## 2. 系統架構

```
ai-smart-industry-map/
├── frontend/                  # React 19 + Vite + TypeScript + Tailwind v4
│   └── src/
│       ├── pages/             # Daily / Topics / TopicDetail / IndustryMap
│       │                      # CompanyDB / Company / AIAnalysis
│       ├── components/        # 依 feature 分目錄，單檔 ≤400 行
│       ├── api/               # TanStack Query hooks
│       └── charts/            # ECharts 封裝（treemap、K線、河流圖、法人柱狀）
├── backend/
│   └── app/
│       ├── api/               # REST routers（Pydantic 進出驗證）
│       ├── pipeline/          # 資料擷取 jobs＋APScheduler 註冊表
│       │   └── sources/       # twse.py / finmind.py / yfinance_.py / mops.py / tdcc.py
│       ├── llm/               # anthropic_.py / openai_compat.py / provider.py
│       ├── db/                # SQLAlchemy models + SQLite（WAL 模式）
│       └── core/              # config(env) / errors / rate_limiter / logging
├── data/
│   ├── seeds/                 # 題材/產業鏈編輯內容（YAML，版控，冪等匯入）
│   └── raw/                   # pipeline 原始回應（保留 7 天，除錯用）
└── Makefile                   # make dev（前後端）/ make seed / make test
```

- **圖表**：Apache ECharts（treemap、K 線、河流圖、柱狀圖原生支援，深色主題可客製）。
- **狀態**：TanStack Query 管快取與輪詢；無全域 store（頁面間共享狀態少）。
- **排程**：APScheduler 掛在 FastAPI lifespan；job 執行紀錄寫 `pipeline_runs`，UI 的「排定更新 / 資料更新於」直接讀此表。

## 3. 資料模型（SQLite，12 張核心表）

| 表 | 關鍵欄位 | 來源 |
|----|----------|------|
| `companies` | ticker(PK), name, market(TW/US/JP), industry_tags, has_futures | TWSE/FinMind |
| `quotes_daily` | ticker+date(PK), OHLCV, change_pct | TWSE OpenAPI / yfinance |
| `index_snapshots` | symbol, price, change, change_pct, fetched_at | yfinance（延遲報價） |
| `institutional_flows` | ticker(可空=市場層), date, foreign_net, trust_net, dealer_net | TWSE/TPEx |
| `margin_balances` | date, 融資/融券 買賣餘額與變化 | TWSE |
| `major_holders` | ticker, week, ratio_400up, holder_count | TDCC 集保 |
| `mops_announcements` | ticker, category(澄清/自結/財務/治理/重大), title, published_at | MOPS |
| `topics` | slug(PK), title, description, market_tab, metrics(JSON: CAGR/規模/規格…), verified_at | seeds |
| `topic_companies` | topic_slug+ticker(PK), chain_level(上/中/下游), category, category_desc, role(龍頭/利基/新興/挑戰), relevance(高/中/低) | seeds |
| `fundamentals` | ticker, month, revenue, yoy, eps, per | FinMind |
| `ai_analyses` | id, ticker, mode(近期/中期/全面), scores(JSON 五面向), reasons(JSON), total, model, created_at | LLM |
| `pipeline_runs` | job_name, scheduled_at, started_at, finished_at, status, error | 系統 |

- 衍生徽章（營收新高/投信買超/外資買超/EPS 年增/處置股）由 `compute_derived` 依規則即時計算寫入快取表 `company_badges`，不進 seeds。
- Seeds YAML 為編輯內容唯一真理來源；`make seed` 冪等 upsert。

## 4. 資料管線（台灣時間）

| Job | 排程 | 重點 |
|-----|------|------|
| `fetch_tw_quotes` | 平日 14:05 | 收盤價、漲跌幅、成交量（上市：TWSE OpenAPI；上櫃：TPEx OpenAPI，兩來源分開實作） |
| `fetch_institutional` | 平日 16:00、17:00 | 三大法人市場層＋個股層 |
| `fetch_margin` | 平日 21:30 | 資券餘額與變化 |
| `fetch_indices` | 盤中每 10 分 | 台指期/費半/S&P500/TSM ADR/NVDA/日經/VIX（yfinance 延遲 15 分，MVP 可接受） |
| `fetch_us_jp_quotes` | 每日 07:00 | 美/日股收盤（僅題材涵蓋的個股清單） |
| `fetch_mops` | 每日 19:05 | 重大訊息，規則分類五類 |
| `fetch_tdcc_holders` | 週六 09:30 | 集保大戶週資料 |
| `fetch_fundamentals` | 每月 11 日 08:00 | 月營收/EPS/PER（FinMind） |
| `compute_derived` | 各 fetch 成功後鏈式觸發 | 產業漲幅排行、強勢股（日/週/月）、treemap 資料、徽章、題材籌碼訊號 |

共通機制：

- 指數退避重試 3 次（1s/4s/16s）→ 失敗標記 stale，不覆蓋舊資料
- 每來源獨立 rate limit（TWSE 3 req/s、FinMind 依免費額度、yfinance 批次）
- 原始回應落地 `data/raw/{source}/{date}/`，保留 7 天
- Job 互不依賴、單一 job 失敗不影響 API 服務

## 5. REST API

```
GET  /api/daily                       # 每日焦點聚合
GET  /api/topics?market=tw|us|jp|chain|etf
GET  /api/topics/{slug}               # 總覽：描述、指標、treemap、籌碼訊號
GET  /api/topics/{slug}/map           # 產業地圖分層資料
GET  /api/companies?query=&industry=&page=
GET  /api/companies/{ticker}          # 個股頁聚合
GET  /api/companies/{ticker}/charts/{kind}   # kline|per_river|institutional|holders
POST /api/ai/analyze {ticker, mode}   # 202 + analysis_id，前端輪詢
GET  /api/ai/analyses/{id}
GET  /api/ai/leaderboard?sort=strong|weak&mode=
GET  /api/search?q=                   # ⌘K：公司＋題材模糊搜尋
GET  /api/meta/pipeline-status        # 各 job 排定/最後成功時間
```

- 錯誤格式統一 `{"error": {"code": "...", "message": "..."}}`；訊息友善、不洩內部細節。
- 進出皆 Pydantic schema 驗證；聚合端點以 SQL view / 查詢組裝，避免 N+1。

## 6. 前端頁面

| 頁面 | 路由 | 重點 |
|------|------|------|
| 每日焦點 | `/` | 指數跑馬燈、法人/資券表（展開歷史）、強勢股排行（市場/週期切換）、MOPS 時間軸（分類 chips＋按日分頁） |
| 題材總覽 | `/topics` | 前三名漲幅焦點卡（漲/跌切換）、題材卡片格（五分頁） |
| 主題總覽 | `/topic/{slug}` | 描述卡、指標、ECharts treemap（單日/單週/單月）、籌碼訊號 |
| 產業地圖 | `/topic/{slug}/map` | 上/中/下游分層手風琴、公司卡片（即時價、角色、徽章、關聯度）、角色分群/差異比較切換 |
| 公司資料庫 | `/companies` | 搜尋、產業篩選、表格＋分頁 |
| 個股頁 | `/c/{ticker}` | 報價頭部、K 線、本益比河流圖、法人買賣超副圖、大戶持股比例 |
| AI 分析 | `/ai` | 排行榜（強勢/弱勢/我的分析）、五面向分數條、觸發分析（模式選擇） |

深色主題為預設與唯一主題（對齊原站）。⌘K Command Palette 全站可用。

## 7. LLM 層

```python
class LLMProvider(Protocol):
    async def complete(self, system: str, user: str, json_schema: dict) -> dict: ...
```

- `AnthropicProvider`：原生 SDK，預設 `claude-sonnet-5`
- `OpenAICompatProvider`：`base_url + api_key + model`（涵蓋公司代理，代理後亦可為 Claude 模型）
- 環境變數：`LLM_PROVIDER=anthropic|openai_compat`、`LLM_BASE_URL`、`LLM_MODEL`、`LLM_API_KEY`
- 分析流程：DB 撈個股脈絡（近 60 日量價、法人、大戶、營收、所屬題材、近期公告）→ 依模式組 prompt → 結構化 JSON（五面向 0-100 分＋各 2-3 句理由）→ schema 驗證入庫；失敗重試 1 次後回友善錯誤
- POST 觸發後非同步執行，前端輪詢結果（202 pattern）

## 8. 錯誤處理

- 外部呼叫（API/DB/LLM/檔案 IO）一律 try/except＋結構化 log（loguru）
- Pipeline 錯誤隔離在 job 層；API 讀不到新資料時回舊資料＋`stale: true`
- 前端：stale 顯示黃色提示條；API 錯誤顯示重試按鈕；ECharts 空資料顯示佔位
- 秘密一律環境變數（`.env`，git-ignored；`.env.example` 版控），缺必要變數啟動即 throw

## 9. 測試策略（標準級）

- **Pipeline parsers**：每個 source 用錄製的真實回應 fixture 跑 pytest（重點：格式漂移防護）
- **API**：httpx TestClient＋記憶體 SQLite，覆蓋主要端點與錯誤路徑
- **compute_derived**：徽章/排行規則的單元測試（邊界：平盤、停牌、新股）
- **前端**：vitest 覆蓋關鍵元件（treemap 資料轉換、排行榜排序、⌘K）
- **修 bug 先寫重現測試**；宣稱通過前必實跑
- E2E（Playwright）列為 MVP 完成後補強項

## 10. 實作切片（垂直切，每片獨立驗收）

1. 專案骨架：前後端腳手架、DB schema、seeds 格式與匯入、Makefile
2. `fetch_tw_quotes` pipeline ＋ 題材總覽頁（第一條端到端路徑）
3. 主題總覽頁：treemap ＋ 籌碼訊號（需 `fetch_institutional`）
4. 產業地圖頁（含徽章 `compute_derived`）
5. 每日焦點：指數/法人/資券/強勢股/MOPS
6. 公司資料庫 ＋ 個股頁四種圖表（需 `fetch_fundamentals`、`fetch_tdcc_holders`）
7. AI 分析：LLM 層、分析流程、排行榜
8. ⌘K 搜尋、pipeline 狀態列、整體打磨

每片流程：Opus 4.8 實作（附驗收條件）→ 另一 Opus 4.8 fresh-context review → 測試實跑通過 → 下一片。

## 附錄 A：矽光子題材 seed（事實資料，擷取自公開頁面 2026-07-11）

- **題材 meta**：光通訊｜矽光子與 CPO；CAGR 45%+；市場規模 10.2（十億美元級）；技術核心 CPO 共同封裝；主力規格 1.6T 導入/3.2T 驗證；商轉節點 2026 大規模量產；產業門檻 台積電生態系/高度客製化。描述文字需改寫。
- **上游**
  - 矽光子製程代工平台：台積電 2330（龍頭/高）、創意 3443（龍頭/中）
  - 外部光源與雷射引擎：聯亞 3081（龍頭/高）、聯鈞 3450（利基/高）、華星光 4979（利基/高）、鼎元 2426（利基/中）
  - 高密度光纖套件與被動元件：光聖 6442（龍頭/高）、波若威 3163（利基/高）、瑞軒 2489（新興/低）
- **中游**
  - CPO 共同封裝與異質整合：日月光投控 3711（龍頭/高）、眾達-KY 4977（挑戰/高）、采鈺 6789（挑戰/中）、上詮 3363（利基/高）、聯鈞 3450（利基/高）＋隱藏 2 家（實作時向使用者確認，推測含訊芯-KY 6451）
  - 高密度光纖陣列 (FAU)：上詮 3363
  - 矽光子測試介面與檢測：日月光投控 3711、旺矽 6223（龍頭/高）、穎崴 6515（利基/高）、宜特 3289（利基/中）
- **下游**：CPO 整合交換器系統（待補充）、AI 算力單元與高效能運算（待補充）
- **成分股總數對帳**：產業地圖具名唯一個股 16 檔＋熱力圖另見的訊芯-KY 6451 ＝ **17 檔**（＝原站籌碼訊號分母 17）。「CPO 分類隱藏 2 家」推測為訊芯-KY＋一家已列名於其他分類的公司（如台積電），實作切片 6 前由使用者登入原站確認，seed 先以 17 檔為準。

## 附錄 B：已知風險

| 風險 | 緩解 |
|------|------|
| 免費 API 格式變動/限流 | 原始回應落地＋parser fixture 測試＋stale 降級 |
| yfinance 指數延遲 15 分 | UI 明示「延遲報價」；未來可換付費源 |
| 登入牆後頁面（個股頁細節等）未完整盤點 | 實作切片 6 前，由使用者於瀏覽器面板登入原站，再接手盤點比對 |
| ETF 持股、Podcast 等無免費來源 | 已排除於 MVP |
