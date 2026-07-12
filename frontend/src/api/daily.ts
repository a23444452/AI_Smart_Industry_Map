import { useQuery } from "@tanstack/react-query";
import { fetchJson } from "./client";

// 型別逐欄對齊後端 backend/app/api/daily.py 的 Pydantic models。
// datetime 欄位序列化為帶 Z 的 UTC ISO string；nullability 依後端定義。

/** 跑馬燈指數現值（IndexRow）。price 恆有值；change/change_pct/fetched_at 可為 null。 */
export interface IndexRow {
  symbol: string;
  name: string;
  price: number;
  change: number | null;
  change_pct: number | null;
  fetched_at: string | null;
}

/** 單一身份別買賣金額（FlowRow）；unit 為來源原名（顯示映射由前端負責）。 */
export interface FlowRow {
  unit: string;
  buy: number | null;
  sell: number | null;
  net: number | null;
}

export interface MarketFlows {
  date: string | null;
  rows: FlowRow[];
}

/** 單一信用交易項目（MarginRow）；item 為來源原名（含單位如「仟元」）。 */
export interface MarginRow {
  item: string;
  buy: number | null;
  sell: number | null;
  prev_balance: number | null;
  today_balance: number | null;
}

export interface Margin {
  date: string | null;
  rows: MarginRow[];
}

/** 漲跌幅榜單列（MoverItem）；close/change_pct 可為 null。 */
export interface MoverItem {
  ticker: string;
  name: string;
  close: number | null;
  change_pct: number | null;
}

export interface Movers {
  day: MoverItem[];
  week: MoverItem[];
  month: MoverItem[];
}

export interface DailyResponse {
  indices: IndexRow[];
  market_flows: MarketFlows;
  margin: Margin;
  movers: Movers;
  announcements_dates: string[];
}

/** 單則重大訊息（AnnouncementItem）；所有欄位皆非 null。 */
export interface AnnouncementItem {
  ticker: string;
  name: string;
  category: string;
  title: string;
  published_at: string;
}

/**
 * 每日焦點聚合 hook：跑馬燈指數／全市場法人與資券／漲跌榜／公告日期。
 * 每 60 秒背景重抓（refetchInterval），維持盤中即時感。
 */
export function useDaily() {
  return useQuery({
    queryKey: ["daily"],
    queryFn: () => fetchJson<DailyResponse>("/api/daily"),
    refetchInterval: 60_000,
  });
}

/**
 * 單日重大訊息 hook。date 為台北日期（YYYY-MM-DD）；date 為 null 時停用查詢。
 * category 有值時帶 query param 篩選分類；為 null 表示全部分類。
 */
export function useAnnouncements(date: string | null, category: string | null) {
  return useQuery({
    queryKey: ["announcements", date, category],
    queryFn: () => {
      const params = new URLSearchParams({ date: date ?? "" });
      if (category !== null) params.set("category", category);
      return fetchJson<AnnouncementItem[]>(
        `/api/daily/announcements?${params.toString()}`,
      );
    },
    enabled: !!date,
  });
}
