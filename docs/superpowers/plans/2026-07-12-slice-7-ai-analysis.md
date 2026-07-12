# 切片 7：AI 分析 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成 `/ai`（AI 評分排行榜＋觸發個股分析）——LLM provider 抽象（Anthropic／OpenAI 相容／**Mock placeholder**）、個股脈絡組裝、五面向評分（題材/基本/技術/籌碼/新聞）、202 非同步分析流程、排行榜。

**Architecture:** 延續方案 A。新增 `ai_analyses` 表、`app/llm/` 模組（provider 抽象）、`app/services/analysis.py`（脈絡組裝＋prompt＋執行）、三個 API 端點（FastAPI BackgroundTasks 做非同步——單行程內背景執行，不引入 queue）。前端 AiPage＋輪詢。

**Tech Stack:** 既有棧。**兩個真實 provider 都用 httpx 直打 API**（Anthropic Messages API／OpenAI chat completions）——不加 SDK 依賴，與全案 httpx 慣例一致。

**Spec:** `docs/superpowers/specs/2026-07-11-ai-stock-map-clone-design.md` §3（ai_analyses）、§5（三端點）、§6（AI 分析頁）、§7（LLM 層）

**執行模式：** 同前。分支 `feat/slice-7`。

## 決策（有意識偏離／使用者指示）

1. **Mock provider 為預設**（使用者指示：placeholder 開工、之後填 key）：`AISM_LLM_PROVIDER=mock|anthropic|openai_compat`，預設 `mock`。MockProvider 產生**確定性**分數（由 ticker＋mode hash 派生＋依實際脈絡資料微調——有 quotes 資料的面向分數合理浮動），回應結構與真 provider 完全相同，端到端可測可 demo。`.env.example` 列四個 LLM 變數＋註解說明切換方式。
2. **不做每日配額**（第一階段既定）；「我的分析」tab 不做（需登入）——排行榜＋觸發分析兩區塊。
3. **非同步用 FastAPI BackgroundTasks**（單行程、無 queue——與方案 A 一致）：`ai_analyses` 表加 `status`（pending/running/done/failed）與 `error` 欄（spec §3 未列，實作需要）。前端輪詢 GET by id（2s 間隔、上限 60s）。
4. **失敗重試 1 次**（spec §7）在 service 層；LLM 回應 JSON schema 驗證失敗也算失敗。
5. **總分**＝五面向加權平均（等權，round 1）——排行榜排序鍵。

## File Structure

```
backend/
├── app/db/models.py               # ＋AiAnalysis
├── app/core/config.py             # ＋llm_provider/llm_model/llm_api_key/llm_base_url
├── app/llm/__init__.py / provider.py（Protocol＋錯誤型別）
│         / anthropic_.py / openai_compat.py / mock.py / factory.py（依 config 選擇）
├── app/services/__init__.py / analysis.py   # build_context/build_prompt/run_analysis
├── app/api/ai.py                  # POST analyze＋GET analyses/{id}＋GET leaderboard
└── tests/test_llm.py / test_analysis.py / test_api_ai.py
frontend/src/
├── api/ai.ts                      # useLeaderboard/useAnalysis(id, 輪詢)/useTriggerAnalysis
├── pages/AiPage.tsx
├── components/ai/ScoreBars.tsx / AnalysisCard.tsx / TriggerPanel.tsx
└── App.tsx / NavBar.tsx           # /ai route、NavBar 啟用（最後一個 disabled 項）
```

---

### Task 1: AiAnalysis 表＋LLM config

**Files:** Modify: `backend/app/db/models.py`, `backend/app/core/config.py`, `.env.example`, `backend/tests/test_models.py`, `backend/tests/test_config.py`

- [ ] 失敗測試→實作→綠：
  - `AiAnalysis`：id auto PK、ticker、mode（近期觀察/中期展望/全面檢視——存字串）、status（pending/running/done/failed）、scores（JSON nullable——`{"題材面":85,...}` 五鍵）、reasons（JSON nullable——五鍵各 list[str]）、total（Float nullable）、model（str nullable——實際使用的 provider:model 標記）、error（Text nullable）＋TimestampMixin；索引 `(ticker, created_at)` 供排行榜/查詢
  - config：`llm_provider: str = "mock"`、`llm_model: str = "claude-sonnet-5"`、`llm_api_key: str = ""`、`llm_base_url: str = ""`（AISM_ prefix；測試驗 env 覆寫）
  - `.env.example` 加四變數＋切換註解（anthropic 需 key；openai_compat 需 base_url+key+model）
- [ ] Commit：`feat: ai_analyses 表與 LLM 設定`

### Task 2: LLM provider 層

**Files:** Create: `backend/app/llm/`（五檔）＋`backend/tests/test_llm.py`

- [ ] 失敗測試→實作→綠（**全部 mock httpx，不打真實 API**）：
  - `provider.py`：`class LLMError(Exception)`（帶 friendly message）＋`LLMProvider` Protocol：**同步** `def complete(system: str, user: str) -> str`（回原始文字——JSON 解析放 service 層，provider 只管傳輸；**不要照抄 spec §7 的 async**——全後端為 sync＋httpx.Client，async 會與同步 Session 混用出問題）
  - `anthropic_.py`：POST `https://api.anthropic.com/v1/messages`（headers x-api-key/anthropic-version、body model/max_tokens/system/messages）→ 取 `content[0].text`；非 200/超時/格式異常 → LLMError（訊息不含 key）
  - `openai_compat.py`：POST `{base_url}/chat/completions`（Bearer、messages system+user）→ `choices[0].message.content`；同錯誤包裝
  - `mock.py`：**確定性、純 seed 派生（不讀脈絡——比「依脈絡微調」簡單且可測）**——`seed = sha256(user prompt 全文)`；五面向分數 60-95 區間派生；reasons 用模板句（標明「模擬分析」）；回傳合法 JSON 字串（與真 provider 輸出同 schema）
  - `factory.py`：`get_provider(settings) -> LLMProvider`；anthropic/openai_compat 缺必要設定（key/base_url）→ 啟動時 raise 帶清楚訊息（缺 key 就 throw——專案錯誤處理底線）；mock 無條件可用
  - 測試：兩真 provider 的成功/非 200/超時/回應缺欄四路徑（monkeypatch httpx）；mock 確定性（同輸入同輸出）；factory 選擇與缺設定 raise
- [ ] Commit：`feat: LLM provider 層（anthropic/openai 相容/mock）`

### Task 3: 分析 service（脈絡＋prompt＋執行）

**Files:** Create: `backend/app/services/analysis.py`＋`backend/tests/test_analysis.py`

- [ ] 失敗測試→實作→綠：
  - `build_context(session, ticker) -> dict`：近 60 日 quotes（收盤/漲跌統計摘要——均值/波動/區間高低、近 5 日走勢）、法人近 20 日淨額合計、大戶比最新值與前週差、最新營收 YoY、PER/PBR、所屬題材（title＋role）、近 5 筆公告標題；**缺資料的段落標注「無資料」不炸**；固定查詢數（重用 queries.py）
  - `build_prompt(context, mode) -> (system, user)`：system 定義角色與**輸出 JSON schema**（五鍵 scores 0-100 int＋五鍵 reasons list[str] 各 2-3 句＋一鍵 summary str）；user 按 mode 調整重點（近期觀察→技術/籌碼權重敘述；中期展望→基本/題材；全面檢視→均衡）；模板為 f-string 常數（可測）
  - `parse_llm_response(text) -> dict`：strip markdown fence、json.loads、schema 驗證（五鍵齊全、分數 0-100、reasons 為 list）——失敗 raise LLMError
  - `run_analysis(engine, analysis_id)`：讀 pending 列 → status=running → build_context/prompt → provider.complete（**失敗重試 1 次**）→ parse → total=等權平均 round 1 → status=done 寫入 scores/reasons/total/model；任何失敗 → status=failed＋error（友善訊息）；**獨立 Session、不經 runner**（這不是排程 job）
  - 測試：context 各段有/無資料、prompt mode 差異、parse 各失敗路徑、run_analysis 成功/重試後成功/兩次失敗（用注入的 fake provider）
- [ ] Commit：`feat: AI 分析 service`

### Task 4: AI API 三端點

**Files:** Create: `backend/app/api/ai.py`＋`backend/tests/test_api_ai.py`；Modify: `backend/app/main.py`

- [ ] 失敗測試→實作→綠：
  1. `POST /api/ai/analyze` body `{ticker, mode}`（Pydantic：mode Literal 三值；ticker 不存在 → 404）→ 建 pending 列 → `BackgroundTasks.add_task(run_analysis, engine, id)` → **202** `{analysis_id}`；**同 ticker+mode 已有 pending/running → 409**（防重複觸發）
  2. `GET /api/ai/analyses/{id}` → `{id,ticker,name,mode,status,scores,reasons,total,model,error,created_at(Z)}`；不存在 404
  3. `GET /api/ai/leaderboard?sort=strong|weak&mode=`（mode optional）→ 每 ticker 取**最新一筆 done** 分析 → 依 total 降/升冪 → `[{rank,ticker,name,mode,scores,total,created_at(Z)}]` top 50
  - 測試用 TestClient（BackgroundTasks 在 TestClient 同步執行——注入 mock provider 讓它跑完，斷言 done 與分數確定性）
- [ ] 實跑 curl（mock provider）：POST → 202 → GET 輪詢到 done → leaderboard 有列，附報告
- [ ] Commit：`feat: AI 分析 API`

### Task 5: 前端 AiPage

**Files:** Create: `frontend/src/api/ai.ts`, `frontend/src/pages/AiPage.tsx`, `frontend/src/components/ai/ScoreBars.tsx`, `AnalysisCard.tsx`, `TriggerPanel.tsx`＋`__tests__`（≥8）；Modify: `App.tsx`, `NavBar.tsx`（AI 分析啟用——**NavBar 全項就位**）

- [ ] `api/ai.ts`（**L1 逐欄**）：useLeaderboard(sort, mode)/useAnalysis(id)（**status pending/running 時 refetchInterval 2s、done/failed 停；輪詢上限 60s**——超時顯示「分析逾時，請稍後重試」安全網，測試涵蓋）/useTriggerAnalysis()（mutation，409 → 友善訊息）
- [ ] 失敗元件測試：ScoreBars（五橫條 0-100、分數字、缺鍵 → 0/"--"）、AnalysisCard（ticker/name/mode chip/五面向/total 大字/時間台北/model 標記——mock 時顯示「模擬分析」badge）、TriggerPanel（ticker 輸入＋mode 三選＋送出 → mutation 呼叫、pending 中 disabled）
- [ ] AiPage：TriggerPanel（頂部）→ 進行中分析卡（輪詢、running spinner、done 即顯示、failed 顯示 error）→ 排行榜（強勢/弱勢 toggle＋mode 篩選 chips＋AnalysisCard 列）＋四態＋「AI 評分僅供參考，不構成投資建議」footer
- [ ] vitest 全綠＋build 綠；Commit：`feat: AI 分析頁`

### Task 6: 端到端驗證＋README

- [ ] 全測試實跑 → `make dev`＋完整流程 curl（POST→輪詢→leaderboard）＋前端 `/ai` 200 → 殺乾淨 → README（三端點、LLM 設定段落——**明示目前為 mock、如何切真實 provider**、切片 1-7 狀態）→ Commit：`docs: README 切片 7`

---

## 驗收條件

1. `/ai` 可觸發分析（mock 2 秒內 done）、看到五面向分數條與排行榜
2. 換 `.env` 的 `AISM_LLM_PROVIDER=anthropic`＋key 即切真實 LLM（**程式碼零改動**——factory 驗證）
3. 全測試綠；NavBar 六項全啟用
4. 品質底線；**key 絕不落 log/error message/版控**

## 注意事項（給實作 subagent）

- L1 教訓必守；UTC+Z；後端錯誤格式照 companies.py 的 JSONResponse `{"error":{"code","message"}}` 模式（**後端沒有名為 ApiError 的類別**——那是前端 client.ts 的 TS class）；409 防重複為 check-then-insert best-effort（單行程 MVP 可接受，註解說明競態）
- LLM 錯誤訊息務必不含 api key（測試斷言 error 文字不含 key 值）
- MockProvider 的輸出 schema 是三 provider 的契約基準——service 測試用它
- BackgroundTasks 在 TestClient 中同步執行完才回應——測試利用此特性；真實 server 為背景執行
