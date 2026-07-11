import { useState } from "react";
import type { MapCategory } from "../../api/topicMap";
import { CompanyCard } from "./CompanyCard";

interface CategoryBlockProps {
  category: MapCategory;
}

// 預設收合時最多顯示的公司數；超過才出現「顯示更多」。
const COLLAPSED_LIMIT = 5;

/** 分類區塊：標題＋公司 grid，公司超過 5 檔可展開/收合；placeholder 顯示待補充空狀態。 */
export function CategoryBlock({ category }: CategoryBlockProps) {
  const { name, desc, placeholder, companies } = category;
  const [expanded, setExpanded] = useState(false);

  const hasMore = companies.length > COLLAPSED_LIMIT;
  const visible =
    hasMore && !expanded ? companies.slice(0, COLLAPSED_LIMIT) : companies;
  const remaining = companies.length - COLLAPSED_LIMIT;

  return (
    <div className="rounded-xl border border-border-line bg-surface p-4">
      {/* 標題列：name ＋ N 家公司 pill */}
      <div className="flex items-center justify-between gap-2">
        <h4 className="font-semibold text-text-main">{name}</h4>
        <span className="shrink-0 rounded-full border border-border-line bg-surface-2 px-2.5 py-0.5 text-xs text-text-dim">
          {companies.length} 家公司
        </span>
      </div>

      {/* 分類描述（null 不渲染） */}
      {desc !== null && <p className="mt-1 text-sm text-text-dim">{desc}</p>}

      {placeholder ? (
        // 待補充空狀態：虛線邊框卡，不渲染公司 grid
        <div className="mt-3 rounded-lg border border-dashed border-border-line px-4 py-6 text-center text-sm text-text-dim">
          待補充
        </div>
      ) : (
        <>
          <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {visible.map((company) => (
              <CompanyCard key={company.ticker} company={company} />
            ))}
          </div>

          {hasMore && (
            <button
              type="button"
              aria-expanded={expanded}
              onClick={() => setExpanded((prev) => !prev)}
              className="mt-3 w-full rounded-lg border border-border-line py-2 text-sm text-text-dim transition-colors hover:bg-surface-2"
            >
              {expanded ? "收合" : `顯示更多 (${remaining})`}
            </button>
          )}
        </>
      )}
    </div>
  );
}
