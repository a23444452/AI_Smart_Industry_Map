import { useCallback, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { fetchJson, postJson } from "./client";

// 型別逐欄對齊後端 backend/app/api/ai.py 的 Pydantic models。
// - AnalysisDetail：結果欄位（scores/reasons/summary/total/model/error）依 status 誠實 nullable。
// - leaderboard 回應為 { items: [...] } envelope；每項含 rank/scores/total/model。
// 五面向鍵名（scores/reasons 的 key）：題材面/基本面/技術面/籌碼面/新聞面
//（單一來源在 backend app/llm/provider.py 的 ASPECTS，順序即計分順序）。

/** 分析狀態：pending/running 為進行中，done 完成，failed 失敗。 */
export type AnalysisStatus = "pending" | "running" | "done" | "failed";

/** 分析模式（三值，與後端 MODES 精確一致）。 */
export type AnalysisMode = "近期觀察" | "中期展望" | "全面檢視";

/** 三種分析模式（順序即 UI 呈現順序，值與後端 services.analysis.MODES 一致）。 */
export const MODES: readonly AnalysisMode[] = [
  "近期觀察",
  "中期展望",
  "全面檢視",
];

/**
 * 五面向鍵名（順序即 scores/reasons 的呈現順序）。
 * 單一來源為後端 app/llm/provider.py 的 ASPECTS；兩端須保持一致。
 */
export const ASPECTS = [
  "題材面",
  "基本面",
  "技術面",
  "籌碼面",
  "新聞面",
] as const;

/** 五面向分數（0-100 整數）；鍵名與後端 ASPECTS 一致。缺鍵由元件守護。 */
export type AspectScores = Record<string, number>;

/** 單筆分析完整欄位（GET /api/ai/analyses/{id}）。 */
export interface AnalysisDetail {
  id: number;
  ticker: string;
  name: string | null;
  mode: string;
  status: AnalysisStatus;
  scores: AspectScores | null;
  reasons: Record<string, string[]> | null;
  summary: string | null;
  total: number | null;
  model: string | null;
  error: string | null;
  created_at: string | null;
}

/** 榜單單列（帶 rank；無 reasons/summary/error/status）。 */
export interface LeaderboardItem {
  rank: number;
  ticker: string;
  name: string | null;
  mode: string;
  scores: AspectScores | null;
  total: number | null;
  model: string | null;
  created_at: string | null;
}

/** 榜單回應 envelope。 */
export interface LeaderboardResponse {
  items: LeaderboardItem[];
}

/** 觸發分析的回應（202 Accepted）。 */
export interface TriggerResponse {
  analysis_id: number;
}

/** 榜單排序：strong 強勢（total 降冪）／weak 弱勢（total 升冪）。 */
export type LeaderboardSort = "strong" | "weak";

/** 輪詢間隔（進行中每 2 秒）。 */
export const POLL_INTERVAL_MS = 2000;
/** 輪詢上限（超過即停止，由頁面顯示逾時提示）。 */
export const POLL_TIMEOUT_MS = 60_000;

/**
 * 依分析狀態與已耗時計算下一次輪詢間隔（純函式，供測試直接覆蓋）。
 * - pending/running 且未逾時 → 每 POLL_INTERVAL_MS 輪詢一次
 * - 已逾時（elapsed ≥ POLL_TIMEOUT_MS）→ false（停止輪詢，安全網）
 * - 其餘（done/failed/undefined）→ false（不輪詢）
 */
export function analysisRefetchInterval(
  status: AnalysisStatus | undefined,
  elapsedMs: number,
): number | false {
  if (status === "pending" || status === "running") {
    if (elapsedMs >= POLL_TIMEOUT_MS) return false;
    return POLL_INTERVAL_MS;
  }
  return false;
}

/**
 * 分析狀態轉為 done 時是否該刷新排行榜（純函式，供 AiPage effect 與測試共用）。
 * 只在「轉變為 done」的瞬間回 true（prev 非 done → next 為 done），避免重複
 * invalidate；首次抓取即為 done（prev 為 undefined）亦視為剛完成、需刷新。
 */
export function shouldRefreshLeaderboard(
  prev: AnalysisStatus | undefined,
  next: AnalysisStatus | undefined,
): boolean {
  return next === "done" && prev !== "done";
}

/**
 * 榜單 hook：queryKey 三參數（sort／mode）——任一變動即重查。
 * @param sort 強勢／弱勢
 * @param mode 模式篩選（null＝全部；有值須與後端 MODES 精確一致）
 */
export function useLeaderboard(sort: LeaderboardSort, mode: string | null) {
  return useQuery({
    queryKey: ["ai-leaderboard", sort, mode],
    queryFn: () => {
      const params = new URLSearchParams({ sort });
      if (mode) params.set("mode", mode);
      return fetchJson<LeaderboardResponse>(
        `/api/ai/leaderboard?${params.toString()}`,
      );
    },
  });
}

/**
 * 單筆分析 hook：id 為 null 時停用；進行中（pending/running）每 2 秒輪詢，
 * done/failed 停止。輪詢上限 60 秒——逾時後停止輪詢並回傳 timedOut=true，
 * 由頁面顯示「分析逾時，請稍後重試」。起始時間以 id 變動為界重置；
 * 逾時後呼叫 restart() 重置起始時間並 refetch，恢復 2 秒輪詢。
 * @param id 分析 id（null＝尚未觸發，停用查詢）
 */
export function useAnalysis(id: number | null) {
  // 以「記住上一個 id」的方式在 id 變動時重置起始時間（React 官方推薦的
  // render 期重置 pattern，避免額外 effect）。
  const startRef = useRef<number>(Date.now());
  const [prevId, setPrevId] = useState<number | null>(id);
  if (id !== prevId) {
    setPrevId(id);
    startRef.current = Date.now();
  }

  const query = useQuery({
    queryKey: ["ai-analysis", id],
    queryFn: () => fetchJson<AnalysisDetail>(`/api/ai/analyses/${id}`),
    enabled: id != null,
    refetchInterval: (q) =>
      analysisRefetchInterval(
        q.state.data?.status,
        Date.now() - startRef.current,
      ),
  });

  const status = query.data?.status;
  const inProgress = status === "pending" || status === "running";
  const timedOut = inProgress && Date.now() - startRef.current >= POLL_TIMEOUT_MS;

  const { refetch } = query;
  // 逾時後重試：重置輪詢起始 timestamp 再 refetch——refetch 觸發 re-render 與
  // refetchInterval 重新評估（elapsed 歸零 → 回到 2 秒輪詢），timedOut 同步解除。
  const restart = useCallback(() => {
    startRef.current = Date.now();
    void refetch();
  }, [refetch]);

  return { ...query, timedOut, restart };
}

/**
 * 觸發分析 mutation：POST /api/ai/analyze。
 * 409（該 ticker+mode 已有進行中的分析）→ ApiError(status 409) 拋出，
 * 由 UI 讀 error.detail 顯示後端訊息。QueryClient 對 mutation 預設不 retry。
 */
export function useTriggerAnalysis() {
  return useMutation({
    mutationFn: (vars: { ticker: string; mode: AnalysisMode }) =>
      postJson<TriggerResponse>("/api/ai/analyze", vars),
  });
}
