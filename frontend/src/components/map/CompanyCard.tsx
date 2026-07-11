import type { MapCompany } from "../../api/topicMap";
import { formatPct, pctColorClass } from "../../lib/format";

interface CompanyCardProps {
  company: MapCompany;
}

// role → 顯示標籤與色系（深色底淺色字，用 Tailwind 內建色）。未知 role 走 fallback。
const ROLE_STYLES: Record<string, { label: string; className: string }> = {
  龍頭: {
    label: "🟢 產業龍頭",
    className: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  },
  利基: {
    label: "🔵 利基專精",
    className: "border-sky-500/40 bg-sky-500/10 text-sky-300",
  },
  新興: {
    label: "🟣 新興初期",
    className: "border-violet-500/40 bg-violet-500/10 text-violet-300",
  },
  挑戰: {
    label: "🟠 成長挑戰",
    className: "border-amber-500/40 bg-amber-500/10 text-amber-300",
  },
};

/** 收盤價：千分位、去除小數尾零（2415 → "2,415"）；null → "--"。 */
function formatClose(close: number | null): string {
  if (close === null) return "--";
  return close.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

/** 公司卡片：純展示元件，緊湊呈現名稱、報價、角色與徽章（台股紅漲綠跌）。 */
export function CompanyCard({ company }: CompanyCardProps) {
  const { ticker, name, role, relevance, close, change_pct, badges } = company;
  // role null → 中性 chip「未分類」；未知 role 原樣顯示、走中性色，不炸。
  const roleStyle = (role !== null ? ROLE_STYLES[role] : undefined) ?? {
    label: role ?? "未分類",
    className: "border-border-line bg-surface-2 text-text-dim",
  };

  return (
    <article className="rounded-lg border border-border-line bg-surface p-3 transition-colors hover:bg-surface-2">
      {/* 上列：name＋ticker | 右上 close＋change_pct */}
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <span className="font-semibold text-text-main">{name}</span>
          <span className="ml-1.5 text-xs text-text-dim">{ticker}</span>
        </div>
        <div className="flex flex-col items-end tabular-nums">
          <span className="text-sm font-semibold text-text-main">
            {formatClose(close)}
          </span>
          <span className={`text-xs ${pctColorClass(change_pct)}`}>
            {formatPct(change_pct)}
          </span>
        </div>
      </div>

      {/* 中列：角色 chip ＋ 關聯度 */}
      <div className="mt-2 flex items-center gap-2">
        <span
          className={`rounded-full border px-2 py-0.5 text-xs ${roleStyle.className}`}
        >
          {roleStyle.label}
        </span>
        {/* relevance null → 顯示「— 關聯度」 */}
        <span className="text-xs text-text-dim">{relevance ?? "—"} 關聯度</span>
      </div>

      {/* 下列：badges chips（空陣列不渲染） */}
      {badges.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {badges.map((badge) => (
            <span
              key={badge}
              className="rounded border border-border-line px-1.5 py-0.5 text-[11px] text-text-dim"
            >
              {badge}
            </span>
          ))}
        </div>
      )}
    </article>
  );
}
