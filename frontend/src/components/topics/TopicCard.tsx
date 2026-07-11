import type { TopicSummary } from "../../api/topics";
import { formatPct, pctColorClass } from "../../lib/format";

interface TopicCardProps {
  topic: TopicSummary;
}

/** 題材卡片：純展示元件，props 進、UI 出（漲跌帶色帶符號，台股紅漲綠跌）。 */
export function TopicCard({ topic }: TopicCardProps) {
  const { title, description, company_count, verified_at, change_pct_avg } =
    topic;

  return (
    <article className="flex flex-col rounded-xl border border-border-line bg-surface p-5 transition-colors hover:bg-surface-2">
      {/* 頂列：小標＋公司數 pill 徽章 */}
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-text-dim">題材更新</span>
        <span className="rounded-full border border-border-line bg-surface-2 px-2.5 py-0.5 text-xs text-text-dim">
          {company_count} 家公司
        </span>
      </div>

      {/* 標題 */}
      <h3 className="mt-3 text-xl font-bold text-text-main">{title}</h3>

      {/* 描述（兩行截斷） */}
      <p className="mt-1.5 line-clamp-2 text-sm text-text-dim">{description}</p>

      {/* 漲跌均值（帶色帶符號） */}
      <div className="mt-4 flex items-baseline gap-2">
        <span className="text-xs text-text-dim">漲跌均值</span>
        <span
          className={`text-lg font-semibold tabular-nums ${pctColorClass(change_pct_avg)}`}
        >
          {formatPct(change_pct_avg)}
        </span>
      </div>

      {/* 底列：探索按鈕（切片 4 才實作）＋核實日期 */}
      <div className="mt-4 flex items-center justify-between border-t border-border-line pt-4">
        <button
          type="button"
          disabled
          title="切片 4 實作"
          className="cursor-not-allowed rounded-lg border border-border-line px-3 py-1.5 text-xs text-text-dim opacity-60"
        >
          探索產業地圖
        </button>
        <span className="text-xs text-text-dim">核實於 {verified_at}</span>
      </div>
    </article>
  );
}
