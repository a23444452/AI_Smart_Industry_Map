import type { TopicSummary } from "../../api/topics";
import { formatPct, pctColorClass } from "../../lib/format";

interface RankFocusCardsProps {
  rank: TopicSummary[];
  direction: "up" | "down";
  onDirectionChange: (direction: "up" | "down") => void;
  /** 首次載入中：顯示焦點區 skeleton（keepPreviousData 下切換方向不會觸發） */
  isLoading?: boolean;
  /** 載入失敗：顯示錯誤語意，避免誤導的「今日尚無資料」 */
  isError?: boolean;
}

// 排行方向 toggle 按鈕組設定
const DIRECTIONS: { value: "up" | "down"; label: string }[] = [
  { value: "up", label: "漲" },
  { value: "down", label: "跌" },
];

/** 今日產業漲幅焦點：標題列＋漲/跌 toggle＋前三名大卡。 */
export function RankFocusCards({
  rank,
  direction,
  onDirectionChange,
  isLoading = false,
  isError = false,
}: RankFocusCardsProps) {
  return (
    <section className="mb-8">
      {/* 標題列：icon＋標題＋漲/跌 toggle */}
      <div className="mb-4 flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-lg font-bold text-text-main">
          <span aria-hidden="true">🔥</span>
          今日台股產業漲幅焦點
        </h2>
        <div className="inline-flex overflow-hidden rounded-lg border border-border-line">
          {DIRECTIONS.map((d) => (
            <button
              key={d.value}
              type="button"
              aria-pressed={direction === d.value}
              onClick={() => onDirectionChange(d.value)}
              className={[
                "px-3 py-1.5 text-sm transition-colors",
                direction === d.value
                  ? "bg-accent text-text-main"
                  : "bg-surface text-text-dim hover:bg-surface-2",
              ].join(" ")}
            >
              {d.label}
            </button>
          ))}
        </div>
      </div>

      {/* 前三名大卡；載入中 skeleton／錯誤語意／空資料佔位 */}
      {isLoading ? (
        <div className="grid gap-4 md:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <div
              key={i}
              data-testid="rank-skeleton"
              className="h-32 animate-pulse rounded-xl border border-border-line bg-surface"
            />
          ))}
        </div>
      ) : isError ? (
        <div className="rounded-xl border border-border-line bg-surface p-8 text-center text-sm text-text-dim">
          焦點載入失敗，請稍後再試。
        </div>
      ) : rank.length === 0 ? (
        <div className="rounded-xl border border-border-line bg-surface p-8 text-center text-sm text-text-dim">
          今日尚無資料
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-3">
          {rank.slice(0, 3).map((topic, i) => (
            <article
              key={topic.slug}
              className="rounded-xl border border-border-line bg-surface p-5"
            >
              <div className="flex items-center justify-between">
                <span className="text-sm font-bold text-text-dim">
                  #{i + 1}
                </span>
                <span className="text-xs text-text-dim">
                  {topic.company_count} 家公司
                </span>
              </div>
              <div
                className={`mt-3 text-3xl font-bold tabular-nums ${pctColorClass(topic.change_pct_avg)}`}
              >
                {formatPct(topic.change_pct_avg)}
              </div>
              <div className="mt-2 text-sm font-medium text-text-main">
                {topic.title}
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
