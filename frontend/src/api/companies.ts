import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { fetchJson } from "./client";
import type {
  KlineItem,
  PerRiverItem,
  InstitutionalItem,
  HoldersItem,
} from "../charts/chartOptions";

// 型別逐欄對齊後端 backend/app/api/companies.py 的 Pydantic models。
// nullable 欄位依後端定義；close/change/change_pct/volume/per/pbr… 皆可為 null。

/** 題材 facet（供清單頁下拉／個股頁題材 chips）。 */
export interface TopicFacet {
  slug: string;
  title: string;
}

/** 清單單列（CompanyListItem）；close/change_pct/per/revenue_yoy 皆可為 null。 */
export interface CompanyListItem {
  ticker: string;
  name: string;
  market: string;
  topics: string[];
  close: number | null;
  change_pct: number | null;
  per: number | null;
  revenue_yoy: number | null;
}

/** 清單回應（CompanyListResponse）；topics_facets 恆為全部 topics（不隨篩選變動）。 */
export interface CompanyListResponse {
  total: number;
  page: number;
  page_size: number;
  items: CompanyListItem[];
  topics_facets: TopicFacet[];
}

/** 最新月營收（LatestRevenue）。 */
export interface LatestRevenue {
  month: string;
  revenue: number | null;
  yoy: number | null;
}

/** 集保大戶（>400 張）持股比（MajorHolderInfo）。 */
export interface MajorHolderInfo {
  week: string;
  ratio_400up: number;
}

/** 個股詳情（CompanyDetail）；報價與估值欄位多為 nullable，呼叫端需守護。 */
export interface CompanyDetail {
  ticker: string;
  name: string;
  market: string;
  close: number | null;
  change: number | null;
  change_pct: number | null;
  volume: number | null;
  topics: TopicFacet[];
  badges: string[];
  per: number | null;
  pbr: number | null;
  dividend_yield: number | null;
  latest_revenue: LatestRevenue | null;
  major_holder: MajorHolderInfo | null;
  quotes_updated_at: string | null;
}

/** 圖表種類（對應後端 charts/{kind} 的 Literal）。 */
export type ChartKind = "kline" | "per_river" | "institutional" | "holders";

/** 各 kind 對應的 item 型別（與 chartOptions 純函式輸入一致）。 */
export interface ChartItemMap {
  kline: KlineItem;
  per_river: PerRiverItem;
  institutional: InstitutionalItem;
  holders: HoldersItem;
}

/** 圖表回應：後端統一包成 { items: [...] }。 */
export interface ChartResponse<K extends ChartKind> {
  items: ChartItemMap[K][];
}

const PAGE_SIZE = 20;

/**
 * 公司清單 hook：可搜尋（ticker 前綴 OR name 包含）、可依 topic 篩選、分頁。
 *
 * queryKey 含 query／topic／page 三參數——三者任一變動即重新查詢。
 * placeholderData: keepPreviousData——翻頁或改條件時沿用前次資料，避免畫面閃爍空白。
 * @param query 搜尋字串（空＝不搜尋）
 * @param topic 題材 slug（空＝不篩選）
 * @param page  頁碼（1-based）
 */
export function useCompanies(query: string, topic: string, page: number) {
  return useQuery({
    queryKey: ["companies", query, topic, page],
    queryFn: () => {
      const params = new URLSearchParams({
        page: String(page),
        page_size: String(PAGE_SIZE),
      });
      if (query) params.set("query", query);
      if (topic) params.set("topic", topic);
      return fetchJson<CompanyListResponse>(`/api/companies?${params.toString()}`);
    },
    placeholderData: keepPreviousData,
  });
}

/**
 * 個股詳情 hook。ticker 為空時停用查詢；查無公司時後端回 404 → ApiError(status 404)。
 * @param ticker 股票代號，例如 "2330"
 */
export function useCompany(ticker: string) {
  return useQuery({
    queryKey: ["company", ticker],
    queryFn: () => fetchJson<CompanyDetail>(`/api/companies/${ticker}`),
    enabled: !!ticker,
  });
}

/**
 * 個股圖表 hook：依 ticker 與 kind 抓取單一圖表資料（{ items: [...] }）。
 * ticker 為空時停用查詢（enabled: !!ticker）；回傳型別依 kind 靜態決定。
 * @param ticker 股票代號
 * @param kind   圖表種類（kline／per_river／institutional／holders）
 */
export function useCompanyChart<K extends ChartKind>(ticker: string, kind: K) {
  return useQuery({
    queryKey: ["company-chart", ticker, kind],
    queryFn: () =>
      fetchJson<ChartResponse<K>>(`/api/companies/${ticker}/charts/${kind}`),
    enabled: !!ticker,
  });
}
