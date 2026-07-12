import type { MarketFlows } from "../../api/daily";
import { formatYi } from "../../lib/format";

interface MarketFlowsTableProps {
  data: MarketFlows;
}

// 身份別顯示映射（來源原名 → 精簡顯示名）；未列於此表者原樣顯示。
const UNIT_LABEL: Record<string, string> = {
  "自營商(自行買賣)": "自營商",
  "外資及陸資(不含外資自營商)": "外資",
  "外資自營商": "外資自營商",
  "自營商(避險)": "自營商避險",
  "投信": "投信",
};

function displayUnit(unit: string): string {
  return UNIT_LABEL[unit] ?? unit;
}

/** net 正紅負綠（0／null → dim）。 */
function netColor(net: number | null): string {
  if (net === null || net === 0) return "text-text-dim";
  return net > 0 ? "text-up" : "text-down";
}

/** 全市場三大法人買賣金額表（最新一日）；空表顯示佔位。 */
export function MarketFlowsTable({ data }: MarketFlowsTableProps) {
  return (
    <div className="rounded-xl border border-border-line bg-surface p-5">
      <h2 className="text-sm font-medium text-text-main">三大法人買賣超</h2>
      <p className="mt-0.5 text-xs text-text-dim">全市場・單位：金額</p>
      {data.rows.length === 0 ? (
        <p className="mt-4 text-sm text-text-dim">暫無法人資料</p>
      ) : (
        <table className="mt-4 w-full text-sm">
          <thead>
            <tr className="text-xs text-text-dim">
              <th className="pb-2 text-left font-normal">身份別</th>
              <th className="pb-2 text-right font-normal">買進</th>
              <th className="pb-2 text-right font-normal">賣出</th>
              <th className="pb-2 text-right font-normal">買賣超</th>
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {data.rows.map((row) => (
              <tr key={row.unit} className="border-t border-border-line">
                <td className="py-2 text-left text-text-main">
                  {displayUnit(row.unit)}
                </td>
                <td className="py-2 text-right text-text-dim">
                  {formatYi(row.buy)}
                </td>
                <td className="py-2 text-right text-text-dim">
                  {formatYi(row.sell)}
                </td>
                <td className={`py-2 text-right ${netColor(row.net)}`}>
                  {formatYi(row.net)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
