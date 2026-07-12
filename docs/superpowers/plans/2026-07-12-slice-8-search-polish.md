# 切片 8：⌘K 搜尋＋整體打磨 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成 ⌘K 全站搜尋（公司＋題材），並收斂累積的打磨待辦（AI 孤兒 running 回收、ticker 驗證、NavBar 動態入口、treemap 空態）。**這是 MVP 最後一個切片。**

**Architecture:** 延續方案 A。`GET /api/search` 輕量端點；前端 CommandPalette（全域 cmd/ctrl+K、鍵盤導航）。

**Spec:** `docs/superpowers/specs/2026-07-11-ai-stock-map-clone-design.md` §5（search 端點）、§6（⌘K 全站）

**執行模式：** 同前。分支 `feat/slice-8`。

## 打磨待辦清單（併入本切片，來源：任務 #59＋歷次 final review minors）

| 項 | 內容 | 歸屬 Task |
|----|------|-----------|
| P1 | AI 孤兒 running：409 檢查加時間下界（active 列 created_at 需在 10 分鐘內，逾期視同可重新觸發） | Task 1 |
| P2 | `AnalyzeRequest.ticker` 驗證（strip＋非空） | Task 1 |
| P3 | NavBar 產業地圖動態入口（topics 快取首筆、fallback 現有常數） | Task 2 |
| P4 | Treemap items 空陣列 → 「暫無資料」佔位（切片 3 遺留） | Task 2 |
| 不做 | leaderboard window 查詢（規模化才需要）、Safari summary flex（無法自動驗證——README known issues 一句話）、差異比較 tab（維持 disabled） | — |

---

### Task 1: search API＋後端打磨

**Files:** Create: `backend/app/api/search.py`, `backend/tests/test_api_search.py`；Modify: `backend/app/main.py`, `backend/app/api/ai.py`（P1/P2）＋對應測試

- [ ] 失敗測試→實作→綠：
  1. `GET /api/search?q=台積` → `{companies: [{ticker,name,market}], topics: [{slug,title}]}`——公司比對 ticker 前綴 OR name contains；題材比對 title contains OR slug 前綴；各 limit 10、依 ticker/slug 升冪；`q` 必填、strip 後空 → 422；`q` 過長（>50 字）→ 422
  2. P1：`ai.py` 的 409 檢查加 `created_at >= utcnow() − ACTIVE_WINDOW_MINUTES(10)` 條件——孤兒 running 逾 10 分鐘不再擋新觸發（註解說明 crash 回收語意）；補測試（插一筆 11 分鐘前的 running → POST 202）
  3. P2：`AnalyzeRequest.ticker` 加 field_validator strip＋非空（空白 → 422）；補測試
- [ ] Commit：`feat: 全站搜尋 API 與 AI 打磨`

### Task 2: CommandPalette＋前端打磨

**Files:** Create: `frontend/src/api/search.ts`, `frontend/src/components/layout/CommandPalette.tsx`＋`__tests__`；Modify: `frontend/src/components/layout/NavBar.tsx`（搜尋按鈕＋P3）、`frontend/src/App.tsx`（palette 掛載）、`frontend/src/charts/Treemap.tsx`（P4）＋測試

- [ ] `api/search.ts`（L1）＋`useSearch(q)`（enabled: q.trim().length>0、debounce 由元件層）
- [ ] 失敗元件測試（≥8）：
  - CommandPalette：開啟時 input autofocus；輸入 → 結果分組（「公司」「題材」標題）；↑↓ 移動 active 項（aria-selected）；Enter → navigate（公司 /c/{ticker}、題材 /topic/{slug}）＋關閉；Esc 關閉；空結果「找不到符合項目」；q 空時顯示提示「輸入代號、公司或題材名稱」
  - 全域快捷鍵：cmd+K/ctrl+K 開啟（window keydown listener、cleanup）
  - P4：Treemap items=[] → 「暫無資料」佔位（不 init chart）
- [ ] 實作：
  - CommandPalette：fixed overlay＋置中卡（深色）、debounce 200ms、鍵盤導航 state、`role="dialog"` aria；掛在 App.tsx（layout 層）
  - NavBar：右側搜尋按鈕（「搜尋…」＋`⌘K` kbd 樣式——點擊也可開啟）＋P3（`useQuery(["topics","tw","up"], ..., { enabled: false })` **純讀快取**——staleTime 擋不住 cold-cache 首抓、`enabled:false` 才真正零請求；取 `topics[0].slug`（非 rank），快取空 → fallback 現有常數）
- [ ] vitest 全綠＋build 綠；Commit：`feat: ⌘K 全站搜尋與前端打磨`

### Task 3: 端到端驗證＋README 最終化

**Files:** Modify: `README.md`

- [ ] 全測試實跑（後端 404＋新增、前端 153＋新增）
- [ ] `make dev` → curl search 端點＋前端全頁面 200 巡檢（/、/topics、/topic/silicon-photonics、…/map、/companies、/c/2330、/ai）→ 殺乾淨
- [ ] README 最終化：search 端點、⌘K 說明、開發狀態改「**MVP 完成（切片 1-8）**」＋已知限制段（Safari summary flex 未驗證、單行程背景任務、mock LLM 預設、排行 universe=已收錄）＋後續 roadmap 段（登入/會員、原站像素比對、全市場 universe）
- [ ] Commit：`docs: README MVP 完成`

---

## 驗收條件

1. 任意頁面按 ⌘K（或點 NavBar 搜尋）→ 輸入「台積」→ 公司/題材分組結果 → Enter 跳轉
2. 打磨四項全落地（P1 孤兒回收測試、P2 422、P3 動態入口、P4 空態）
3. 全測試綠；全頁面巡檢 200
4. README 反映 MVP 完成狀態

## 注意事項

- L1／UTC+Z／錯誤格式慣例沿用
- CommandPalette 的全域 listener 務必 cleanup（unmount）；Esc/route change 皆關閉
- search 端點固定 2 查詢（companies＋topics）
