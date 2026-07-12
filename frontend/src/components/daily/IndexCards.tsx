import type { IndexRow } from "../../api/daily";
import { formatPct, pctColorClass } from "../../lib/format";

interface IndexCardsProps {
  indices: IndexRow[];
}

/** 單張指數卡：名稱、現值（千分位）、漲跌幅（formatPct、紅漲綠跌；null → "--" dim）。 */
function IndexCard({ row }: { row: IndexRow }) {
  const pct = row.change_pct;
  const color = pct === null ? "text-text-dim" : pctColorClass(pct);
  return (
    <div className="rounded-xl border border-border-line bg-surface px-4 py-3">
      <p className="truncate text-xs text-text-dim">{row.name}</p>
      <p className="mt-1 text-lg font-semibold tabular-nums text-text-main">
        {row.price.toLocaleString("en-US")}
      </p>
      <p className={`mt-0.5 text-sm tabular-nums ${color}`}>
        {pct === null ? "--" : formatPct(pct)}
      </p>
    </div>
  );
}

/** 跑馬燈指數卡列：7 張橫向網格；空陣列顯示佔位。 */
export function IndexCards({ indices }: IndexCardsProps) {
  if (indices.length === 0) {
    return (
      <p className="rounded-xl border border-border-line bg-surface px-4 py-6 text-center text-sm text-text-dim">
        暫無指數資料
      </p>
    );
  }
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-7">
      {indices.map((row) => (
        <IndexCard key={row.symbol} row={row} />
      ))}
    </div>
  );
}
