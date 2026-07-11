/**
 * Canvas 圖表用色彩常數（與 index.css @theme 對應）。
 *
 * ECharts canvas renderer 讀不到 CSS 變數（--color-*），故於此維護一份色票複本。
 * 改 index.css 色票時需同步本檔，兩邊才不會走鐘。
 *
 * 對應關係：
 *   CHART_BG      ← --color-bg          #0b1220（頁面底／色塊分隔邊框）
 *   CHART_SURFACE ← --color-surface     #111a2e（卡片底／tooltip 底）
 *   CHART_BORDER  ← --color-border-line #24304d（分隔線／tooltip 邊框）
 *   CHART_TEXT    ← --color-text-main   #e6ebf5（主文字／tooltip 文字）
 *   UP_COLORS     ← 基於 --color-up     #f6465d（紅漲，四級由淺到深）
 *   DOWN_COLORS   ← 基於 --color-down   #2ebd85（綠跌，四級由淺到深）
 *   FLAT_COLOR    ← 持平灰塊（change_pct === 0）
 */

/** 頁面底色，也作為色塊之間的分隔邊框 */
export const CHART_BG = "#0b1220";
/** 卡片／tooltip 底色 */
export const CHART_SURFACE = "#111a2e";
/** 分隔線／tooltip 邊框色 */
export const CHART_BORDER = "#24304d";
/** 主文字色 */
export const CHART_TEXT = "#e6ebf5";

// 色階（台股慣例：紅漲綠跌）。四級由淺到深對應幅度 <1% / ≥1% / ≥3% / ≥5%。
// 紅系基於 --color-up #f6465d、綠系基於 --color-down #2ebd85 的深淺變化。
export const UP_COLORS = ["#f99aa8", "#f6465d", "#cf2942", "#a01d30"] as const;
export const DOWN_COLORS = ["#86e3c0", "#2ebd85", "#1f9268", "#14664a"] as const;
/** 持平（change_pct === 0）灰塊 */
export const FLAT_COLOR = "#3a4358";
