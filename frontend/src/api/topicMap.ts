import { useQuery } from "@tanstack/react-query";
import { fetchJson } from "./client";

// 型別對齊後端 topic_map.py 的 Pydantic models（role/relevance/close/change_pct
// 皆可為 null，呼叫端需守護）。
export interface MapCompany {
  ticker: string;
  name: string;
  role: string;
  relevance: string;
  close: number | null;
  change_pct: number | null;
  badges: string[];
}

export interface MapCategory {
  name: string;
  desc: string | null;
  // placeholder=true 表示尚未填入公司的骨架分類，companies 恆空。
  placeholder: boolean;
  companies: MapCompany[];
}

export interface MapLevel {
  // 產業鏈層級：上游／中游／下游。
  level: string;
  categories: MapCategory[];
}

export interface TopicMap {
  slug: string;
  title: string;
  levels: MapLevel[];
}

/**
 * 產業地圖 hook：依 slug 抓取單一題材的產業鏈地圖。
 * 模式沿用 useTopicDetail；查無題材時後端回 404 → fetchJson throw ApiError。
 * @param slug 題材代碼，例如 "silicon-photonics"
 */
export function useTopicMap(slug: string) {
  return useQuery({
    queryKey: ["topic-map", slug],
    queryFn: () => fetchJson<TopicMap>(`/api/topics/${slug}/map`),
    enabled: slug.length > 0,
  });
}
