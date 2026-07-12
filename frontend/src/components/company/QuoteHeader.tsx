import { Link } from "react-router-dom";
import type { CompanyDetail } from "../../api/companies";
import { formatPct, pctColorClass } from "../../lib/format";

interface QuoteHeaderProps {
  company: CompanyDetail;
}

/** 收盤大字：千分位、保留小數；null → "--"。 */
function formatClose(close: number | null): string {
  if (close === null) return "--";
  return close.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

/** 漲跌值（絕對）：帶符號兩位小數；null → "--"。 */
function formatChange(change: number | null): string {
  if (change === null) return "--";
  const sign = change > 0 ? "+" : "";
  return `${sign}${change.toFixed(2)}`;
}

/**
 * 成交量顯示為「張」：後端 volume 單位為股，÷1000 取整為張、加千分位。
 * null → "--"。
 */
function formatLots(volume: number | null): string {
  if (volume === null) return "--";
  return `${Math.floor(volume / 1000).toLocaleString("en-US")} 張`;
}

/** 一般數值兩位小數；null → "--"。 */
function formatNum(n: number | null): string {
  if (n === null) return "--";
  return n.toFixed(2);
}

/** 百分比兩位小數（自帶 % 尾）；null → "--"。 */
function formatPercent(n: number | null): string {
  if (n === null) return "--";
  return `${n.toFixed(2)}%`;
}

/** 單一估值指標欄（標籤在上、值在下）。 */
function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border-line bg-surface-2 px-3 py-2">
      <p className="text-xs text-text-dim">{label}</p>
      <p className="mt-0.5 text-sm font-medium tabular-nums text-text-main">
        {value}
      </p>
    </div>
  );
}

/**
 * 個股報價抬頭：名稱／代號、收盤大字、漲跌值與幅（帶色帶符號）、成交量（張），
 * 估值列（PER／PBR／殖利率／營收年增／大戶持股比，缺值 --），徽章 chips 與題材 chips
 * （題材為連往題材詳情頁的 Link）。
 */
export function QuoteHeader({ company }: QuoteHeaderProps) {
  const {
    ticker,
    name,
    close,
    change,
    change_pct,
    volume,
    topics,
    badges,
    per,
    pbr,
    dividend_yield,
    latest_revenue,
    major_holder,
  } = company;
  const changeColor = pctColorClass(change_pct);

  return (
    <div className="rounded-xl border border-border-line bg-surface p-6">
      {/* 名稱／代號 */}
      <div className="flex items-baseline gap-2">
        <h1 className="text-2xl font-bold text-text-main">{name}</h1>
        <span className="text-sm text-text-dim tabular-nums">{ticker}</span>
      </div>

      {/* 收盤大字 ＋ 漲跌值／幅（帶色帶符號） */}
      <div className="mt-3 flex items-end gap-3">
        <span className="text-4xl font-bold tabular-nums text-text-main">
          {formatClose(close)}
        </span>
        <span className={`pb-1 text-lg font-medium tabular-nums ${changeColor}`}>
          {formatChange(change)} ({formatPct(change_pct)})
        </span>
      </div>

      {/* 成交量（張） */}
      <p className="mt-2 text-sm text-text-dim tabular-nums">
        成交量 {formatLots(volume)}
      </p>

      {/* 估值列 */}
      <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-5">
        <Metric label="本益比" value={formatNum(per)} />
        <Metric label="股價淨值比" value={formatNum(pbr)} />
        <Metric label="殖利率" value={formatPercent(dividend_yield)} />
        <Metric
          label="營收年增"
          value={formatPct(latest_revenue?.yoy ?? null)}
        />
        <Metric
          label="大戶持股比"
          value={formatPercent(major_holder?.ratio_400up ?? null)}
        />
      </div>

      {/* 徽章 chips（空陣列不渲染） */}
      {badges.length > 0 && (
        <div className="mt-4 flex flex-wrap gap-1.5">
          {badges.map((badge) => (
            <span
              key={badge}
              className="rounded border border-border-line px-2 py-0.5 text-xs text-text-dim"
            >
              {badge}
            </span>
          ))}
        </div>
      )}

      {/* 題材 chips（Link → 題材詳情頁；空陣列不渲染） */}
      {topics.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {topics.map((t) => (
            <Link
              key={t.slug}
              to={`/topic/${t.slug}`}
              className="rounded-full border border-border-line bg-surface-2 px-3 py-1 text-xs text-text-dim transition-colors hover:text-text-main"
            >
              {t.title}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
