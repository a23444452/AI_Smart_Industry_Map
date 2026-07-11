import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { fetchJson } from "./client";

// 型別對齊後端 Pydantic（snake_case 保持一致；description/verified_at 後端可為 null）
export interface TopicSummary {
  slug: string;
  title: string;
  description: string | null;
  market_tab: "tw" | "us" | "jp" | "chain" | "etf";
  company_count: number;
  verified_at: string | null;
  change_pct_avg: number | null;
}

export interface TopicsResponse {
  topics: TopicSummary[];
  rank: TopicSummary[];
}

export type Market = TopicSummary["market_tab"];

/**
 * 題材列表 hook：依市場分頁與排行方向抓取，30 秒輪詢一次。
 * 切換 market/direction 時以 keepPreviousData 保留舊資料，避免整頁閃 skeleton。
 * @param market 市場分頁（tw/us/jp/chain/etf）
 * @param direction 排行焦點方向（up 漲／down 跌）
 */
export function useTopics(market: Market, direction: "up" | "down") {
  return useQuery({
    queryKey: ["topics", market, direction],
    queryFn: () =>
      fetchJson<TopicsResponse>(
        `/api/topics?market=${market}&direction=${direction}`,
      ),
    refetchInterval: 30_000,
    placeholderData: keepPreviousData,
  });
}
