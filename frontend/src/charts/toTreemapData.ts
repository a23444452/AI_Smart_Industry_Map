import { formatPct } from "../lib/format";

/** treemap 單筆輸入：一檔個股的當期漲跌 */
export interface TreemapInput {
  ticker: string;
  name: string;
  change_pct: number | null;
}

/** 輸出給 ECharts treemap series.data 的節點 */
export interface EChartsTreemapNode {
  /** ticker 原值，供點擊/查找用（非 ECharts 內建欄位，但可透傳） */
  ticker: string;
  /** ECharts 以 name 作為 label 內容：「名稱\n+1.25%」 */
  name: string;
  /** 面積權重（|change_pct|，下限 0.3） */
  value: number;
  /** 依漲跌方向與幅度分級的色塊 */
  itemStyle: { color: string };
}

// 色票（台股慣例：紅漲綠跌）。四級由淺到深對應幅度 <1% / ≥1% / ≥3% / ≥5%。
// 紅系基於 --color-up #f6465d、綠系基於 --color-down #2ebd85 的深淺變化。
export const UP_COLORS = ["#f99aa8", "#f6465d", "#cf2942", "#a01d30"] as const;
export const DOWN_COLORS = ["#86e3c0", "#2ebd85", "#1f9268", "#14664a"] as const;
/** 持平（change_pct === 0）灰塊 */
export const FLAT_COLOR = "#3a4358";

/** value 下限：跌 0.01% 的股票也要看得見 */
const MIN_VALUE = 0.3;

/**
 * 依幅度絕對值取 4 級索引：<1% → 0、≥1% → 1、≥3% → 2、≥5% → 3。
 * 邊界含下界（≥）。
 */
function magnitudeLevel(absPct: number): 0 | 1 | 2 | 3 {
  if (absPct >= 5) return 3;
  if (absPct >= 3) return 2;
  if (absPct >= 1) return 1;
  return 0;
}

/** 依漲跌方向與幅度回傳色塊 */
function colorFor(changePct: number): string {
  if (changePct === 0) return FLAT_COLOR;
  const level = magnitudeLevel(Math.abs(changePct));
  return changePct > 0 ? UP_COLORS[level] : DOWN_COLORS[level];
}

/**
 * 將個股漲跌清單轉為 ECharts treemap 節點陣列。
 * - 排除 change_pct 為 null 的項目
 * - value = max(|change_pct|, 0.3)
 * - 顏色依漲跌方向（紅漲綠跌）與幅度分 4 級
 * - name = 「{名稱}\n{+x.xx%}」（重用 formatPct）
 */
export function toTreemapData(items: TreemapInput[]): EChartsTreemapNode[] {
  const result: EChartsTreemapNode[] = [];
  for (const item of items) {
    if (item.change_pct === null) continue;
    const changePct = item.change_pct;
    result.push({
      ticker: item.ticker,
      name: `${item.name}\n${formatPct(changePct)}`,
      value: Math.max(Math.abs(changePct), MIN_VALUE),
      itemStyle: { color: colorFor(changePct) },
    });
  }
  return result;
}
