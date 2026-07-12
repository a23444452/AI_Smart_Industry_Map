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

/**
 * 將 UTC ISO 時間字串格式化為台北時區「時:分」（如 "09:05"）；解析失敗回 null。
 */
export function formatTimeTaipei(iso: string | null): string | null {
  if (iso === null) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleTimeString("zh-TW", {
    timeZone: "Asia/Taipei",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

const YI = 100_000_000; // 一億
const WAN = 10_000; // 一萬

/**
 * 將以「元」為單位的金額壓縮為易讀字串（台股慣例大額用億）。
 * - null／NaN → "--"
 * - 絕對值 ≥ 1 億 → 「X.X億」（一位小數，整數時去除 .0，如 94.9億／5億）
 * - 絕對值 < 1 億 → 四捨五入到萬、加千分位，如「1,235萬」；
 *   若四捨五入後滿 10,000 萬（如 99,995,000）則進位為「1億」，不顯示「10,000萬」
 * - 負數帶前綴 ASCII "-"（與 formatPct／toLocaleString 一致）
 */
export function formatYi(n: number | null): string {
  if (n === null || Number.isNaN(n)) return "--";
  const sign = n < 0 ? "-" : "";
  const abs = Math.abs(n);
  const wan = Math.round(abs / WAN);
  if (abs >= YI || wan >= 10_000) {
    const yi = (abs / YI).toFixed(1).replace(/\.0$/, "");
    return `${sign}${yi}億`;
  }
  return `${sign}${wan.toLocaleString("en-US")}萬`;
}
