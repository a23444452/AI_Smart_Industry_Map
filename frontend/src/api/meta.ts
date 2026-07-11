import { useQuery } from "@tanstack/react-query";
import { fetchJson } from "./client";

// 型別對齊後端 /api/meta/pipeline-status（時間戳為帶 Z 的 UTC ISO string，可為 null）。
export interface PipelineStatusItem {
  job_name: string;
  last_status: string;
  last_success_at: string | null;
  last_finished_at: string | null;
}

/**
 * pipeline 健康狀態 hook：每 60 秒輪詢一次，供頁尾「資料更新於」使用。
 */
export function usePipelineStatus() {
  return useQuery({
    queryKey: ["pipeline-status"],
    queryFn: () => fetchJson<PipelineStatusItem[]>("/api/meta/pipeline-status"),
    refetchInterval: 60_000,
  });
}
