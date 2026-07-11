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

/**
 * 將 UTC ISO 時間字串格式化為台北時區日期（如 "2026/7/11"）。
 * null 或無法解析時回傳 null，由呼叫端決定是否渲染。
 */
export function formatDateTaipei(iso: string | null): string | null {
  if (iso === null) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleDateString("zh-TW", { timeZone: "Asia/Taipei" });
}
