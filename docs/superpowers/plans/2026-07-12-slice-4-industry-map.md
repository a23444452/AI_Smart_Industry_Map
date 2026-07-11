# 切片 4：產業地圖頁 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成 `/topic/{slug}/map` 產業地圖頁——上/中/下游供應鏈分層、分類卡、公司卡片（收盤價、漲跌幅、角色標籤、關聯度、徽章），與主題總覽頁互相切換。

**Architecture:** 資料已全部就位（`Topic.chain_meta` 分類骨架＋`topic_companies` 歸屬＋`quotes_daily`/`institutional_flows`）。新增 `GET /api/topics/{slug}/map` 聚合端點；徽章**於 API 層即時計算**（見決策）；前端新增 MapPage 與公司卡片元件。

**Tech Stack:** 既有棧，無新依賴

**Spec:** `docs/superpowers/specs/2026-07-11-ai-stock-map-clone-design.md` §5（map 端點）、§6（產業地圖頁）、§3（company_badges）

**執行模式：** 同前——Opus 4.8 實作＋兩階段 review；同 task 連續失敗 2 次回報主對話。分支 `feat/slice-4`。

## 決策（有意識偏離 spec 之處）

1. **徽章即時計算、不建 `company_badges` 快取表**：spec §3 規劃 compute_derived 寫快取表，那是為全市場數百檔設計的。目前題材成員僅 17 檔、map 端點一次聚合查詢即可算完，建表＋job 屬過度設計（YAGNI）。等公司資料庫（切片 6）擴到全市場再遷移。
2. **本切片可算的徽章只有三種**：`有股票期貨`（companies.has_futures）、`外資買超`、`投信買超`（institutional_flows 最新交易日 net > 0）。`營收新高`/`EPS年增` 需 fundamentals（切片 6）、`處置股` 無免費來源——皆不做。
3. **「差異比較」檢視不做**：原站該功能在登入牆後未盤點，本切片只做「角色分群」主檢視；tab 顯示但 disabled（title="尚未實作"）。
4. **「加入收藏」不做**（登入功能，第一階段排除）。

**併入本切片的 follow-ups（任務 #29）：** F3=ECharts lazy-load、F4=treemap 色值與 @theme 同源常數、F5=detail 404 OpenAPI 宣告。

---

## File Structure

```
backend/
├── app/api/topic_map.py           # GET /api/topics/{slug}/map（新 router 檔，避免 topics.py 突破 400 行）
└── tests/test_api_topic_map.py
frontend/src/
├── api/topicMap.ts                # 型別＋useTopicMap hook
├── pages/TopicMapPage.tsx         # /topic/:slug/map
├── components/map/ChainLevelSection.tsx   # 上/中/下游區段（手風琴）
├── components/map/CategoryBlock.tsx       # 分類卡（名稱/desc/公司數/placeholder）
├── components/map/CompanyCard.tsx         # 公司卡片（價格/漲跌/角色/關聯度/徽章）
├── components/map/__tests__/…
├── pages/TopicDetailPage.tsx      # 產業鏈 tab → Link（修改）
├── charts/theme.ts                # F4：色彩常數單一來源（新）
└── App.tsx                        # route＋F3 lazy（修改）
```

---

### Task 1: map API

**Files:** Create: `backend/app/api/topic_map.py`, `backend/tests/test_api_topic_map.py`；Modify: `backend/app/main.py`（include router）

- [ ] **Step 1:** 失敗測試（conftest TestClient；seed 真實 seeds＋手插已知 quotes/flows）：
  1. `GET /api/topics/silicon-photonics/map` → 200：
     ```json
     {
       "slug": "silicon-photonics", "title": "光通訊｜矽光子與 CPO",
       "levels": [
         {
           "level": "上游",
           "categories": [
             {
               "name": "矽光子製程代工平台", "desc": "...", "placeholder": false,
               "companies": [
                 {
                   "ticker": "2330", "name": "台積電",
                   "role": "龍頭", "relevance": "高",
                   "close": 2415.0, "change_pct": -2.03,
                   "badges": ["有股票期貨", "投信買超"]
                 }
               ]
             }
           ]
         },
         { "level": "中游", ... }, { "level": "下游", ... }
       ]
     }
     ```
  2. 分類順序照 `chain_meta` 骨架；placeholder 分類 `companies: []`＋`placeholder: true`
  3. 同 ticker 跨分類各自出現（3711 在中游兩個分類都有卡）
  4. 徽章規則：`有股票期貨`←has_futures；`外資買超`/`投信買超`←該 ticker institutional_flows **最新一筆** net > 0（插已知資料驗證正反例）；無 flows → 無該類徽章
  5. close/change_pct ← quotes_daily 最新日（change_pct round 2）；無 quotes → null
  6. 未知 slug → 404（與 detail 同格式）；chain_meta 為 null 的 topic → `levels: []` 不炸
- [ ] **Step 2:** FAIL
- [ ] **Step 3:** 實作 `topic_map.py`：固定查詢數（topic get＋members join companies＋最新 quotes＋最新 flows，各一次、Python 組裝）；Pydantic models（MapCompany/MapCategory/MapLevel/TopicMap）；`response_model` 宣告＋404 responses 宣告（順帶示範 F5 的作法）；main.py include router
- [ ] **Step 4:** `uv run pytest -v` 全綠（111＋新增）
- [ ] **Step 5:** 實跑 `curl localhost:8400/api/topics/silicon-photonics/map | python3 -m json.tool | head -50` 附報告；Commit：`feat: topic map API`

---

### Task 2: F5 detail 404 OpenAPI＋F3/F4 前端優化

**Files:** Modify: `backend/app/api/topics.py`（404 responses 宣告）、`frontend/src/App.tsx`（lazy）、`frontend/src/charts/Treemap.tsx`、`frontend/src/charts/toTreemapData.ts`；Create: `frontend/src/charts/theme.ts`

- [ ] **Step 1:** `topics.py` detail 端點補 `responses={404: {...}}` 宣告（描述 error 格式）
- [ ] **Step 2:** `charts/theme.ts`：集中色彩常數（BG/BORDER/SURFACE/TEXT/UP_COLORS/DOWN_COLORS/FLAT），註解標明「與 index.css @theme 對應，canvas 讀不到 CSS 變數故複本於此，改色需兩處同步」；Treemap.tsx 與 toTreemapData.ts 改 import 此模組
- [ ] **Step 3:** F3：TopicDetailPage 的 `<Treemap>` 改 `React.lazy`＋`<Suspense fallback={skeleton}>`（動態 import 讓 echarts 從主 bundle 拆出）
- [ ] **Step 4:** `npx vitest run` 全綠＋`npm run build`——**驗證 bundle 拆分**：build 輸出應出現獨立 echarts chunk，主 chunk 明顯縮小（附前後對比數字）
- [ ] **Step 5:** Commit：`refactor: echarts lazy-load、色彩同源與 404 文件`

---

### Task 3: 前端 map API 層＋公司卡片元件

**Files:** Create: `frontend/src/api/topicMap.ts`, `frontend/src/components/map/CompanyCard.tsx`, `CategoryBlock.tsx`, `ChainLevelSection.tsx`＋`__tests__/CompanyCard.test.tsx`, `__tests__/CategoryBlock.test.tsx`

- [ ] **Step 1:** `api/topicMap.ts`：型別對齊 Task 1 response＋`useTopicMap(slug)`（queryKey ["topic-map", slug]）
- [ ] **Step 2:** 失敗元件測試：
  - CompanyCard：name＋ticker、close（無 → "--"）、change_pct 紅漲綠跌帶符號（重用 formatPct/pctColorClass）、角色標籤（龍頭→🟢 產業龍頭／利基→🔵 利基專精／新興→🟣 新興初期／挑戰→🟠 成長挑戰，各自色系 chip）、`{relevance} 關聯度`、badges chips（空陣列不渲染徽章區）
  - CategoryBlock：名稱＋desc＋`N 家公司`；placeholder → 顯示「待補充」空狀態；**公司 >5 檔時預設收合、「顯示更多 (N)」展開**（state）
- [ ] **Step 3:** FAIL → **Step 4:** 實作三元件（深色 @theme tokens；ChainLevelSection＝level 標題（上游/中游/下游＋分類數）＋預設展開的手風琴（`<details open>` 或 state 擇一）；檔案各 ≤120 行）
- [ ] **Step 5:** vitest 全綠；Commit：`feat: 產業地圖元件`

---

### Task 4: TopicMapPage＋路由串接

**Files:** Create: `frontend/src/pages/TopicMapPage.tsx`；Modify: `frontend/src/App.tsx`（route）、`frontend/src/pages/TopicDetailPage.tsx`（產業鏈 tab → Link）、`frontend/src/components/topics/TopicCard.tsx`（「探索產業地圖」按鈕 → Link 啟用）

- [ ] **Step 1:** TopicMapPage `/topic/:slug/map`：
  - 頂部：回題材總覽 Link＋title＋「產業內部結構」副標
  - 總覽/產業鏈 toggle：總覽=Link 到 `/topic/{slug}`、產業鏈=active；旁邊「差異比較」disabled（title="尚未實作"）
  - 主體：levels.map → ChainLevelSection → CategoryBlock grid → CompanyCard
  - 四態：skeleton／404（同 detail 頁模式）／錯誤卡 refetch／正常
- [ ] **Step 2:** TopicDetailPage 的「產業鏈」tab 改為 `<Link to={...}/map>`（拿掉 disabled）；TopicCard「探索產業地圖」按鈕改 `<Link>` 啟用
- [ ] **Step 3:** 元件測試沿用既有模式補 1-2 個關鍵斷言（頁面 tab 連結存在）；`npx vitest run` 全綠＋build 綠
- [ ] **Step 4:** Commit：`feat: 產業地圖頁`

---

### Task 5: 端到端驗證＋README

**Files:** Modify: `README.md`

- [ ] **Step 1:** 全測試實跑（後端＋前端）
- [ ] **Step 2:** `make dev` → curl `/api/topics/silicon-photonics/map`（levels 三層、公司卡含徽章）＋前端 `/topic/silicon-photonics/map` 200 → 殺乾淨
- [ ] **Step 3:** README：API 表加 map 端點、開發狀態改切片 1-4 完成＋連結本 plan
- [ ] **Step 4:** Commit：`docs: README 切片 4`

---

## 驗收條件

1. `/topic/silicon-photonics/map` 顯示上/中/下游 8 分類、17 檔不重複公司（約 20 張卡——3450/3363/3711 跨分類重複出現）（真實收盤價/漲跌）、角色與關聯度標籤、徽章（有股票期貨×6 檔＋依真實法人資料的買超徽章）、下游兩個「待補充」placeholder
2. 總覽↔產業鏈雙向切換、TopicCard「探索產業地圖」可點
3. 全測試綠（宣稱前實跑）；echarts 已從主 bundle 拆出（build 輸出佐證）
4. 品質底線同前（無 print/console.log、檔案 ≤400、datetime 帶 Z）

## 注意事項（給實作 subagent）

- chain_meta 骨架格式見 `app/db/seed.py` docstring 與 `data/seeds/silicon-photonics.yaml`；分類 desc 與 placeholder 皆存於 chain_meta，公司歸屬（role/relevance）在 topic_companies（PK: topic_slug+ticker+category）
- 徽章語意「最新一筆 flows」＝該 ticker 的 institutional_flows 依 date 降冪第一筆（不是全市場最新日——個股可能缺某日資料）。**注意口徑差異**：總覽頁 chip_signals 用「近 5 交易日加總」、map 徽章用「最新一筆」——API docstring 需註明此差異與理由，避免日後被當 bug
- 分類歸屬 join 條件**同時比對 `chain_level`＋`category` 名稱**（本 seed 分類名全域唯一，但不留跨 level 同名錯配的隱性假設）
- 原站文案禁止逐字複製（分類 desc 已是改寫版、直接用 DB 值）
- runner/UTC/ApiError 契約沿用；前端錯誤處理沿用 ApiError.status 模式
