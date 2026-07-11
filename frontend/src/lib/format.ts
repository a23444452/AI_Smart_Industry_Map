/**
 * 將漲跌百分比格式化為帶符號兩位小數字串。
 * 正數帶 +（如 +1.25%）、負數帶 -（如 -0.95%）、null 回傳 "--"。
 */
export function formatPct(value: number | null): string {
  if (value === null || Number.isNaN(value)) return "--";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

/**
 * 依漲跌值回傳對應色彩 utility class（台股慣例：紅漲綠跌）。
 * 正數 text-up（紅）、負數 text-down（綠）、0 或 null text-text-dim。
 */
export function pctColorClass(value: number | null): string {
  if (value === null || value === 0) return "text-text-dim";
  return value > 0 ? "text-up" : "text-down";
}
