import { Link } from "react-router-dom";
import type { CompanyListItem } from "../../api/companies";
import { formatPct, pctColorClass } from "../../lib/format";

interface CompanyTableProps {
  items: CompanyListItem[];
}

/** 收盤價：千分位、去除多餘小數尾零（1234.5 → "1,234.5"）；null → "--"。 */
function formatClose(close: number | null): string {
  if (close === null) return "--";
  return close.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

/** 本益比：兩位小數；null → "--"。 */
function formatPer(per: number | null): string {
  if (per === null) return "--";
  return per.toFixed(2);
}

/** 公司清單表：各列代號（Link → 個股頁）／名稱／收盤／漲跌幅（帶色）／PER／營收 YoY。 */
export function CompanyTable({ items }: CompanyTableProps) {
  if (items.length === 0) {
    return (
      <div className="rounded-xl border border-border-line bg-surface p-8 text-center text-sm text-text-dim">
        查無符合條件的公司
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-border-line bg-surface">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-xs text-text-dim">
            <th className="px-4 py-3 text-left font-normal">代號</th>
            <th className="px-4 py-3 text-left font-normal">名稱</th>
            <th className="px-4 py-3 text-right font-normal">收盤</th>
            <th className="px-4 py-3 text-right font-normal">漲跌幅</th>
            <th className="px-4 py-3 text-right font-normal">本益比</th>
            <th className="px-4 py-3 text-right font-normal">營收年增</th>
          </tr>
        </thead>
        <tbody>
          {items.map((c) => (
            <tr
              key={c.ticker}
              className="border-t border-border-line transition-colors hover:bg-surface-2"
            >
              <td className="px-4 py-3 text-left tabular-nums">
                <Link
                  to={`/c/${c.ticker}`}
                  className="text-accent transition-colors hover:underline"
                >
                  {c.ticker}
                </Link>
              </td>
              <td className="px-4 py-3 text-left text-text-main">{c.name}</td>
              <td className="px-4 py-3 text-right tabular-nums text-text-main">
                {formatClose(c.close)}
              </td>
              <td
                className={`px-4 py-3 text-right tabular-nums ${pctColorClass(c.change_pct)}`}
              >
                {formatPct(c.change_pct)}
              </td>
              <td className="px-4 py-3 text-right tabular-nums text-text-dim">
                {formatPer(c.per)}
              </td>
              <td
                className={`px-4 py-3 text-right tabular-nums ${pctColorClass(c.revenue_yoy)}`}
              >
                {formatPct(c.revenue_yoy)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
