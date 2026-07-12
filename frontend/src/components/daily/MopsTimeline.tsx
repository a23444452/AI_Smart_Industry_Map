import { useState } from "react";
import type { AnnouncementItem } from "../../api/daily";
import { useAnnouncements } from "../../api/daily";
import { formatDateTaipei, formatTimeTaipei } from "../../lib/format";

interface MopsTimelineProps {
  /** 近 7 個有公告的台北日期（YYYY-MM-DD），降冪。空陣列 → 佔位。 */
  dates: string[];
}

// 分類 chips：「全部」對應 category=null，其餘傳分類名做 query 篩選。
const CATEGORIES = [
  { label: "全部", value: null },
  { label: "澄清回應", value: "澄清回應" },
  { label: "自結", value: "自結" },
  { label: "財務數據", value: "財務數據" },
  { label: "公司治理", value: "公司治理" },
  { label: "重大事件", value: "重大事件" },
] as const;

/** 單則公告卡：分類小 chip、標題 line-clamp-2、代號名稱、發布時間（台北）。 */
function AnnouncementCard({ item }: { item: AnnouncementItem }) {
  const date = formatDateTaipei(item.published_at);
  const time = formatTimeTaipei(item.published_at);
  return (
    <div className="rounded-lg border border-border-line bg-surface-2 p-3">
      <span className="inline-block rounded bg-surface px-2 py-0.5 text-xs text-text-dim">
        {item.category}
      </span>
      <p className="mt-2 line-clamp-2 text-sm text-text-main">{item.title}</p>
      <p className="mt-2 text-xs text-text-dim">
        {item.ticker} {item.name}
        {date !== null && (
          <span className="ml-2 tabular-nums">
            {date} {time ?? ""}
          </span>
        )}
      </p>
    </div>
  );
}

/** 重大訊息時間軸：日期分頁＋分類 chips＋公告卡列表（接 useAnnouncements）。 */
export function MopsTimeline({ dates }: MopsTimelineProps) {
  const [activeDate, setActiveDate] = useState<string | null>(dates[0] ?? null);
  const [category, setCategory] = useState<string | null>(null);
  const { data, isLoading } = useAnnouncements(activeDate, category);

  if (dates.length === 0) {
    return (
      <div className="rounded-xl border border-border-line bg-surface p-5">
        <h2 className="text-sm font-medium text-text-main">重大訊息</h2>
        <p className="mt-4 text-sm text-text-dim">近期暫無公告</p>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-border-line bg-surface p-5">
      <h2 className="text-sm font-medium text-text-main">重大訊息</h2>

      <div className="mt-3 flex flex-wrap gap-1">
        {dates.map((d) => (
          <button
            key={d}
            type="button"
            aria-pressed={activeDate === d}
            onClick={() => setActiveDate(d)}
            className={[
              "rounded-lg px-3 py-1.5 text-xs tabular-nums transition-colors",
              activeDate === d
                ? "bg-accent text-text-main"
                : "bg-surface-2 text-text-dim hover:text-text-main",
            ].join(" ")}
          >
            {d.slice(5)}
          </button>
        ))}
      </div>

      <div className="mt-3 flex flex-wrap gap-1">
        {CATEGORIES.map((c) => (
          <button
            key={c.label}
            type="button"
            aria-pressed={category === c.value}
            onClick={() => setCategory(c.value)}
            className={[
              "rounded-full px-3 py-1 text-xs transition-colors",
              category === c.value
                ? "bg-accent text-text-main"
                : "bg-surface-2 text-text-dim hover:text-text-main",
            ].join(" ")}
          >
            {c.label}
          </button>
        ))}
      </div>

      <div className="mt-4">
        {isLoading ? (
          <p className="text-sm text-text-dim">載入中…</p>
        ) : !data || data.length === 0 ? (
          <p className="text-sm text-text-dim">此日暫無公告</p>
        ) : (
          <div className="grid gap-2">
            {data.map((item, i) => (
              <AnnouncementCard key={`${item.ticker}-${i}`} item={item} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
