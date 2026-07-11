import { useQuery } from "@tanstack/react-query";
import { fetchJson } from "./client";

// 型別對齊後端 Pydantic（datetime 欄位序列化為帶 Z 的 UTC ISO string，可為 null）。
export interface TreemapItem {
  ticker: string;
  name: string;
  change_pct: number | null;
}

export interface ChipSignalsData {
  window_days: number;
  total: number;
  foreign_buy: number;
  trust_buy: number;
  // 自營商（大戶）口徑切片 4 才定義，後端目前恆為 null。
  major_buy: number | null;
  updated_at: string | null;
}

export interface TopicDetail {
  slug: string;
  title: string;
  description: string | null;
  metrics: Record<string, string>;
  verified_at: string | null;
  treemap: { day: TreemapItem[]; week: TreemapItem[]; month: TreemapItem[] };
  chip_signals: ChipSignalsData;
  quotes_updated_at: string | null;
}

/**
 * 題材詳情 hook：依 slug 抓取單一題材完整資料。
 * staleTime 沿用全域設定；查無題材時後端回 404 → fetchJson throw（error.message 含 "404"）。
 * @param slug 題材代碼，例如 "silicon-photonics"
 */
export function useTopicDetail(slug: string) {
  return useQuery({
    queryKey: ["topic", slug],
    queryFn: () => fetchJson<TopicDetail>(`/api/topics/${slug}`),
    enabled: slug.length > 0,
  });
}
