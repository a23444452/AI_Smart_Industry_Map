import { useState } from "react";
import type { MoverItem, Movers } from "../../api/daily";
import { formatPct, pctColorClass } from "../../lib/format";

interface MoversRankingProps {
  movers: Movers;
}

const TABS = [
  { value: "day", label: "日" },
  { value: "week", label: "週" },
  { value: "month", label: "月" },
] as const;

type Period = (typeof TABS)[number]["value"];

function Row({ item, rank }: { item: MoverItem; rank: number }) {
  return (
    <tr className="border-t border-border-line">
      <td className="py-2 pr-2 text-right text-xs text-text-dim">{rank}</td>
      <td className="py-2 pr-2 text-left tabular-nums text-text-main">
        {item.ticker}
      </td>
      <td className="py-2 pr-2 text-left text-text-dim">{item.name}</td>
      <td className="py-2 pr-2 text-right tabular-nums text-text-main">
        {item.close === null ? "—" : item.close.toLocaleString("en-US")}
      </td>
      <td
        className={`py-2 text-right tabular-nums ${pctColorClass(item.change_pct)}`}
      >
        {formatPct(item.change_pct)}
      </td>
    </tr>
  );
}

/** 漲跌幅榜：日／週／月分頁（aria-pressed），各列排名／代號／名稱／收盤／漲跌幅。 */
export function MoversRanking({ movers }: MoversRankingProps) {
  const [period, setPeriod] = useState<Period>("day");
  const list = movers[period];

  return (
    <div className="rounded-xl border border-border-line bg-surface p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-sm font-medium text-text-main">漲幅排行</h2>
        <div className="flex gap-1">
          {TABS.map((tab) => (
            <button
              key={tab.value}
              type="button"
              aria-pressed={period === tab.value}
              onClick={() => setPeriod(tab.value)}
              className={[
                "rounded-lg px-3 py-1.5 text-xs transition-colors",
                period === tab.value
                  ? "bg-accent text-text-main"
                  : "bg-surface-2 text-text-dim hover:text-text-main",
              ].join(" ")}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>
      <p className="mt-1 text-xs text-text-dim">排行範圍：已收錄個股</p>
      {list.length === 0 ? (
        <p className="mt-4 text-sm text-text-dim">此期間暫無排行資料</p>
      ) : (
        <table className="mt-3 w-full text-sm">
          <thead>
            <tr className="text-xs text-text-dim">
              <th className="pb-2 pr-2 text-right font-normal">#</th>
              <th className="pb-2 pr-2 text-left font-normal">代號</th>
              <th className="pb-2 pr-2 text-left font-normal">名稱</th>
              <th className="pb-2 pr-2 text-right font-normal">收盤</th>
              <th className="pb-2 text-right font-normal">漲跌幅</th>
            </tr>
          </thead>
          <tbody>
            {list.map((item, i) => (
              <Row key={item.ticker} item={item} rank={i + 1} />
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
