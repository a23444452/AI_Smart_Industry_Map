# 切片 3：主題總覽頁（treemap＋籌碼訊號） — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成 `/topic/{slug}` 主題總覽頁——產業描述卡、關鍵指標、產業漲跌 treemap 熱力圖（單日/單週/單月）、籌碼訊號（外資/投信），並補上三大法人資料管線與歷史回填。

**Architecture:** 延續方案 A。新增 `institutional_flows` 表與兩條資料來源（TWSE T86、TPEx 三大法人）；週/月漲跌由 `quotes_daily` 歷史計算（一次性 backfill 35 個交易日）；前端新增 ECharts treemap 封裝與 TopicDetailPage。

**Tech Stack:** 既有棧＋Apache ECharts（前端新依賴，thin React wrapper 自寫、不加 echarts-for-react）

**Spec:** `docs/superpowers/specs/2026-07-11-ai-stock-map-clone-design.md` §4（fetch_institutional）、§5（GET /api/topics/{slug}）、§6（主題總覽頁）

**執行模式（使用者指定）：** 每 task 派 Opus 4.8 subagent 實作＋兩階段 review（spec→quality）；同 task 連續失敗 2 次停止回報主對話（Fable 5）。分支 `feat/slice-3`。

**併入本切片的 follow-ups：**
- F1（原 task #19）：API datetime 序列化統一補 UTC 標記（`Z` 尾碼），前端以 UTC 解析
- F2（原 task #20）：前端串 `/api/meta/pipeline-status` 顯示「資料更新於」

**明確不做（YAGNI）：**
- 處置股黃點標記（無穩定免費來源）
- 籌碼訊號的「大戶」欄（需 TDCC 週資料，切片 6）——API 回 `null`、UI 顯示「—」
- 總覽/產業鏈 sub-tab 的產業鏈內容（切片 4）——tab 存在但 disabled

---

## File Structure（本計畫新增/修改）

```
backend/
├── app/db/models.py               # ＋InstitutionalFlow 表
├── app/pipeline/sources/
│   ├── twse_t86.py                # 上市三大法人（per-day all-stock）
│   ├── tpex_institutional.py      # 上櫃三大法人（per-day all-stock）
│   ├── twse_history.py            # 上市個股月 K 歷史（backfill 用）
│   └── tpex_history.py            # 上櫃個股月歷史（backfill 用）
├── app/pipeline/jobs.py           # ＋fetch_institutional、backfill_quotes
├── app/pipeline/scheduler.py      # ＋fetch_institutional cron（平日 16:10、17:10）
├── app/api/topics.py              # ＋GET /api/topics/{slug}（聚合端點）
├── app/api/serializers.py         # F1：naive UTC → ISO＋Z 共用 helper
├── cli.py                         # ＋backfill 指令
├── scripts/record_fixtures.py     # ＋4 個新端點錄製
└── tests/…                        # 對應測試＋fixtures
frontend/src/
├── charts/Treemap.tsx             # ECharts thin wrapper（useRef＋useEffect）
├── pages/TopicDetailPage.tsx      # /topic/{slug}
├── components/topic/MetricsCard.tsx / ChipSignals.tsx / DataFreshness.tsx
├── api/topicDetail.ts             # useTopicDetail hook＋型別
├── api/meta.ts                    # F2：usePipelineStatus hook
└── App.tsx                        # ＋route；TopicCard 連結到 /topic/{slug}
```

**責任邊界不變：** sources 只抓＋解析；jobs 過濾＋upsert；API 只讀 DB；前端 api/ 層集中網路。

---

### Task 1: InstitutionalFlow model

**Files:** Modify: `backend/app/db/models.py`；Create: 測試併入 `backend/tests/test_models.py`

- [ ] **Step 1:** 失敗測試：建表含 `institutional_flows`；roundtrip（ticker+date 複合 PK、foreign_net/trust_net/dealer_net 為 int 張數、nullable）
- [ ] **Step 2:** 跑測試 → FAIL
- [ ] **Step 3:** 實作 `InstitutionalFlow`：`ticker`＋`date`(ISO str) 複合 PK、`foreign_net`/`trust_net`/`dealer_net`（`Mapped[int | None]`，單位：股）、TimestampMixin。不加 FK 到 companies（來源涵蓋全市場，先過濾再入庫，與 quotes_daily 同策略——quotes_daily 也無 FK，維持一致）
- [ ] **Step 4:** 測試 PASS
- [ ] **Step 5:** Commit：`feat: institutional_flows 表`

---

### Task 2: 三大法人 sources（fixtures-first）

**Files:** Create: `backend/app/pipeline/sources/twse_t86.py`, `.../tpex_institutional.py`, `backend/tests/fixtures/twse_t86.json`, `tpex_institutional.json`；Modify: `backend/scripts/record_fixtures.py`, `backend/tests/test_sources.py`

- [ ] **Step 1（先做）:** 擴充 `record_fixtures.py` 錄製真實回應並人工檢視欄位（**欄位以真實回應為準**，以下為假設）：
  - 上市 T86：`https://www.twse.com.tw/rwd/zh/fund/T86?date={YYYYMMDD}&selectType=ALLBUT0999&response=json`（假設回 `{fields, data}` 表格式；外資買賣超、投信買賣超、自營商買賣超欄位）
  - 上櫃：`https://www.tpex.org.tw/openapi/v1/tpex_daily_insti_trading`（若 OpenAPI 無此資料集，改用 web 端點 `.../web/stock/3insti/daily_trade/3itrade_hedge_result.php?d={ROC日期}&se=EW&t=D`——實測擇一可用者）
  - 注意：這兩個端點**需要 date 參數**（與切片 2 的最新快照端點不同），錄製時用最近一個交易日
- [ ] **Step 2:** 失敗測試（fixtures、不打網路）：`parse(raw) -> list[dict]` 輸出 `{ticker, name, foreign_net, trust_net, dealer_net, date}`；數字去逗號、負數正確；假日/無資料回應（`data` 空或 `stat != "OK"`）→ 回空 list 不 raise
- [ ] **Step 3:** 跑測試 → FAIL
- [ ] **Step 4:** 實作：`fetch(date: str) -> raw`（date ISO，內部轉端點格式；沿用 `_common.get_json`——若 web 端點非 list 回應，放寬 `get_json` 或加 `get_json_dict`，二擇一並更新契約註解）＋`parse(raw)`；自營商淨額 = 自營商(自行買賣)＋自營商(避險)合計（欄位以真實回應為準，於報告說明）
- [ ] **Step 5:** 測試 PASS；Commit：`feat: TWSE/TPEx 三大法人 sources`

---

### Task 3: 歷史行情 sources（backfill 用，fixtures-first）

**Files:** Create: `backend/app/pipeline/sources/twse_history.py`, `.../tpex_history.py`＋fixtures；Modify: `record_fixtures.py`, `test_sources.py`

- [ ] **Step 1（先做）:** 錄製：
  - 上市個股月 K：`https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date={YYYYMM01}&stockNo={ticker}&response=json`
  - 上櫃個股月歷史：`https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock?code={ticker}&date={ROC 年/月}&response=json`（若此端點格式不符，改試 st43 舊端點；實測擇一）
  - 各錄 2330（上市）與 3081（上櫃）一個月份
- [ ] **Step 2:** 失敗測試：`parse(raw, ticker)` 輸出 list of `{ticker, date(ISO), open, high, low, close, volume, change_pct=None}`（歷史端點通常無漲跌幅欄——由 backfill job 後算或留 None，treemap 週/月不需要單日 change_pct）；ROC 日期轉換；千分位、`--` 處理
- [ ] **Step 3:** FAIL → **Step 4:** 實作（`fetch(ticker, year, month)`；rate limit：每請求間 `time.sleep(0.4)`）→ **Step 5:** PASS；Commit：`feat: 個股歷史行情 sources`

---

### Task 4: fetch_institutional job＋scheduler＋backfill CLI

**Files:** Modify: `backend/app/pipeline/jobs.py`, `scheduler.py`, `cli.py`, `Makefile`；Create: 測試併入 `backend/tests/test_jobs.py`

- [ ] **Step 1:** 失敗測試（monkeypatch sources）：
  1. `fetch_institutional(session)`：兩來源→過濾 companies 已知 ticker→upsert `institutional_flows`（date 以來源為準）；重跑冪等；SourceFetchError 上拋
  2. `backfill_quotes(session, days=35)`：對 companies 每檔呼叫歷史 source（該 ticker 上市端點無資料→改試上櫃）、upsert `quotes_daily`，**不覆蓋已存在的 (ticker,date) 列**（保留 fetch_tw_quotes 寫入的 change_pct）；回傳寫入筆數（**僅供直呼測試用**——run_job 會丟棄回傳值，CLI 驗證用 sqlite3 查數）
     - 抓取月數**迴圈補到每檔 ≥35 個交易日為止（上限 3 個月）**，不受執行日在月初/月底影響
     - **單檔失敗 try/except 跳過並 log warning**（不讓一檔壞掉觸發 runner 全量重試）；SourceFetchError 以外的例外同樣兜住
  3. `backfill_institutional(session, days=10)`：對近 10 個「日曆日」逐日呼叫 T86/TPEx（週末/假日空回應自然跳過）、upsert
- [ ] **Step 2:** FAIL → **Step 3:** 實作三個 job fn（遵守 runner 契約：不 commit/rollback）；scheduler 加 `fetch_institutional` cron（平日 16:10 與 17:10 各一發，同 job id 加 suffix；冪等 upsert 所以重複執行無害）；cli 加 `backfill` 指令（依序跑 backfill_quotes＋backfill_institutional，經 `run_job`）；Makefile 加 `backfill:` target
- [ ] **Step 4:** 測試 PASS（全套件）
- [ ] **Step 5:** **實跑一次真實 backfill**（`make backfill`，17 檔 × 2 月份 × sleep 0.4s ≈ 1-2 分鐘）：報告附 sqlite3 查詢——quotes_daily 筆數（應 ≥ 17×20）、institutional_flows 筆數、任一檔的近 5 日法人淨額樣本
- [ ] **Step 6:** Commit：`feat: fetch_institutional 與歷史回填`

---

### Task 5: F1 UTC 序列化＋GET /api/topics/{slug}

**Files:** Create: `backend/app/api/serializers.py`, `backend/tests/test_api_topic_detail.py`；Modify: `backend/app/api/topics.py`, `backend/app/api/meta.py`

- [ ] **Step 1:** 失敗測試：
  1. `to_utc_iso(naive_dt)` → `"2026-07-11T09:02:29Z"`（None→None）；`/api/meta/pipeline-status` 的時間欄位帶 `Z` 尾碼（F1 迴歸）。**機制注意**：既有 `PipelineStatusItem` 欄位是 `datetime`，Pydantic 自動序列化不帶 Z——需把欄位改 `str | None` 並以 helper 轉換，或用 `field_serializer`，二擇一
  2. `GET /api/topics/silicon-photonics` → 200：
     ```json
     {
       "slug": "...", "title": "...", "description": "...", "metrics": {...}, "verified_at": "...",
       "treemap": {
         "day":   [{"ticker","name","change_pct"}],
         "week":  [{"ticker","name","change_pct"}],
         "month": [{"ticker","name","change_pct"}]
       },
       "chip_signals": {"window_days":5,"total":17,"foreign_buy":N,"trust_buy":M,"major_buy":null,"updated_at":"...Z"},
       "quotes_updated_at": "...Z"
     }
     ```
     - `day` change_pct＝quotes_daily 最新日；`week`＝(最新 close ÷ 5 個交易日前 close −1)×100、`month`＝21 個交易日前，**依該 ticker 實際存在的交易日排序取偏移**，不足時該 ticker 回 null；全部 round(2)
     - `chip_signals`：每檔取近 5 個交易日（該 ticker institutional_flows 最新 5 筆）`SUM(foreign_net)>0` 計入 foreign_buy，trust 同理；updated_at＝institutional_flows 最新 date
  3. 未知 slug → 404 `{"error":{"code":"not_found",...}}`；無 quotes 資料 → treemap 空陣列不炸
- [ ] **Step 2:** FAIL → **Step 3:** 實作（單一端點內查詢次數 O(1)~O(3)：一次撈該 topic 成員近 22 個交易日 quotes、一次撈近 5 筆 flows per ticker（window function 或 Python 分組皆可，17 檔資料量小）；Pydantic response models）
- [ ] **Step 4:** 全套件 PASS
- [ ] **Step 5:** Commit：`feat: topic detail API 與 UTC 序列化`

---

### Task 6: 前端 ECharts treemap 封裝

**Files:** Create: `frontend/src/charts/Treemap.tsx`, `frontend/src/__tests__/Treemap.test.tsx`；Modify: `frontend/package.json`

- [ ] **Step 1:** `npm i echarts`（只 import `echarts/core`＋`TreemapChart`＋必要 renderer/components，tree-shaken）
- [ ] **Step 2:** 失敗測試（jsdom 下 ECharts 可 init 於固定尺寸 div；測資料轉換函式為主）：`toTreemapData(items)`——block value＝`|change_pct|`（null→排除）、漲→紅色系（#f6465d 深淺依幅度）、跌→綠色系、0→灰；label 含 `name\n+x.xx%`
- [ ] **Step 3:** FAIL → **Step 4:** 實作 `<Treemap items={...} />`：useRef＋useEffect init/dispose、resize observer、深色 tooltip；轉換邏輯抽純函式 `toTreemapData`（可測）
- [ ] **Step 5:** vitest PASS＋build 綠；Commit：`feat: ECharts treemap 封裝`

---

### Task 7: TopicDetailPage＋路由＋F2 資料更新於

**Files:** Create: `frontend/src/pages/TopicDetailPage.tsx`, `frontend/src/api/topicDetail.ts`, `frontend/src/api/meta.ts`, `frontend/src/components/topic/MetricsCard.tsx`, `ChipSignals.tsx`, `DataFreshness.tsx`＋元件測試；Modify: `frontend/src/App.tsx`, `frontend/src/components/topics/TopicCard.tsx`

- [ ] **Step 1:** `api/topicDetail.ts` 型別對齊 Task 5 response（datetime 欄位 `string`——已帶 Z，`new Date()` 直接正確）＋`useTopicDetail(slug)`；`api/meta.ts` `usePipelineStatus()`（60s refetch）
- [ ] **Step 2:** 失敗元件測試：
  - MetricsCard：metrics JSON 渲染成 label/value 格線
  - ChipSignals：`foreign_buy/total` 顯示「外資 4/17」；`major_buy null` → 「大戶 —」
  - DataFreshness：給 `last_success_at`（UTC ISO）→ 顯示台北時間「資料更新於 下午2:05」（`toLocaleTimeString("zh-TW", {timeZone:"Asia/Taipei"})`）；stale → 黃色提示
- [ ] **Step 3:** FAIL → **Step 4:** 實作：
  - TopicDetailPage `/topic/:slug`：描述卡（title/description/CAGR＋市場規模 badge）→ 總覽/產業鏈 toggle（產業鏈 disabled title="切片 4"）→ 關鍵指標 MetricsCard → treemap 區塊（單日/單週/單月 toggle、`<Treemap>`、DataFreshness 掛 quotes_updated_at）→ ChipSignals（近 5 個交易日副標＋updated_at）
  - 四態：skeleton／錯誤卡 refetch／404 顯示「找不到此題材」＋回題材總覽連結
  - TopicCard：title 區塊包 `<Link to={`/topic/${slug}`}>`（原「探索產業地圖」按鈕維持 disabled）
  - TopicsPage 頁尾掛 DataFreshness（F2：fetch_tw_quotes 的 last_success_at）
- [ ] **Step 5:** vitest 全綠＋build 綠；Commit：`feat: 主題總覽頁`

---

### Task 8: 端到端驗證＋README

**Files:** Modify: `README.md`

- [ ] **Step 1:** 冷啟動：`rm -f backend/data/aism.db && make seed && make fetch && make backfill`——sqlite3 驗證 quotes ≥ 340 筆、institutional_flows > 0
- [ ] **Step 2:** `make dev`：curl `/api/topics/silicon-photonics` 驗證 treemap 三 period 有值（week/month 非全 null）、chip_signals 非全 0；瀏覽 `http://localhost:5173/topic/silicon-photonics` 回 200；殺乾淨
- [ ] **Step 3:** 全測試實跑（後端＋前端），輸出附報告
- [ ] **Step 4:** README 更新：backfill 指令、新 API、切片 3 完成狀態
- [ ] **Step 5:** Commit：`docs: README 切片 3`

---

## 驗收條件

1. `make seed && make fetch && make backfill && make dev` 冷啟動成功
2. `/topic/silicon-photonics` 顯示描述卡、指標、可切換週期的 treemap（真實資料）、籌碼訊號（外資/投信 X/17）、資料更新於（台北時間）
3. 後端 pytest＋前端 vitest 全綠（宣稱前實跑）
4. 品質底線：無 print/console.log、無硬編碼秘密、檔案 ≤400 行、datetime 全帶 Z

## 注意事項（給實作 subagent）

- **fixtures 先於 parser**（Task 2/3 的四個新端點都要先錄真實回應）；rwd/web 端點格式與 OpenAPI 不同（`{stat, fields, data}` 表格式），欄位以實錄為準
- 歷史/法人端點對假日回空——parser 回空 list，不 raise
- runner 契約：job fn 不得 commit/rollback
- backfill 不覆蓋既有 (ticker,date) 列
- 台股紅漲綠跌；datetime naive UTC 存 DB、序列化帶 Z
- 原站文案禁止逐字複製
