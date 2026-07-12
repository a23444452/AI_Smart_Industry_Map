import { useQuery } from "@tanstack/react-query";
import { fetchJson } from "./client";

// 型別對齊後端 backend/app/api/search.py 的 Pydantic models：
// - SearchCompany：ticker/name/market
// - SearchTopic：slug/title
// - SearchResponse：{ companies, topics }（各 ≤10）

/** 搜尋結果的公司列（對齊後端 SearchCompany）。 */
export interface SearchCompany {
  ticker: string;
  name: string;
  market: string;
}

/** 搜尋結果的題材列（對齊後端 SearchTopic）。 */
export interface SearchTopic {
  slug: string;
  title: string;
}

/** 全站搜尋回應 envelope（公司與題材各 ≤10）。 */
export interface SearchResponse {
  companies: SearchCompany[];
  topics: SearchTopic[];
}

/**
 * 全站搜尋 hook：GET /api/search?q=。
 * - enabled：q strip 後非空才發請求（空字串不打 API，後端會回 422）。
 * - staleTime 30 秒：同一關鍵字短時間內重開命令面板不重抓。
 * queryKey 帶 strip 後的 q，確保「abc」與「 abc 」共用快取。
 * @param q 查詢字串（ticker/slug 前綴或 name/title 包含）
 */
export function useSearch(q: string) {
  const trimmed = q.trim();
  return useQuery({
    queryKey: ["search", trimmed],
    queryFn: () =>
      fetchJson<SearchResponse>(`/api/search?q=${encodeURIComponent(trimmed)}`),
    enabled: trimmed.length > 0,
    staleTime: 30_000,
  });
}
