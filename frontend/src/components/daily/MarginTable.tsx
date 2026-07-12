import type { Margin } from "../../api/daily";

interface MarginTableProps {
  data: Margin;
}

/** 數字千分位；null → "—"。單位隨 item 名（如「仟元」）已含在項目名，故不換算。 */
function num(v: number | null): string {
  return v === null ? "—" : v.toLocaleString("en-US");
}

/** 全市場信用交易餘額表（最新一日）；item 原名列，數值直接千分位不換算單位。 */
export function MarginTable({ data }: MarginTableProps) {
  return (
    <div className="rounded-xl border border-border-line bg-surface p-5">
      <h2 className="text-sm font-medium text-text-main">信用交易餘額</h2>
      <p className="mt-0.5 text-xs text-text-dim">全市場・單位見項目名</p>
      {data.rows.length === 0 ? (
        <p className="mt-4 text-sm text-text-dim">暫無資券資料</p>
      ) : (
        <table className="mt-4 w-full text-sm">
          <thead>
            <tr className="text-xs text-text-dim">
              <th className="pb-2 text-left font-normal">項目</th>
              <th className="pb-2 text-right font-normal">買進</th>
              <th className="pb-2 text-right font-normal">賣出</th>
              <th className="pb-2 text-right font-normal">前日餘額</th>
              <th className="pb-2 text-right font-normal">今日餘額</th>
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {data.rows.map((row) => (
              <tr key={row.item} className="border-t border-border-line">
                <td className="py-2 text-left text-text-main">{row.item}</td>
                <td className="py-2 text-right text-text-dim">{num(row.buy)}</td>
                <td className="py-2 text-right text-text-dim">{num(row.sell)}</td>
                <td className="py-2 text-right text-text-dim">
                  {num(row.prev_balance)}
                </td>
                <td className="py-2 text-right text-text-main">
                  {num(row.today_balance)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
