import type { MapLevel } from "../../api/topicMap";
import { CategoryBlock } from "./CategoryBlock";

interface ChainLevelSectionProps {
  level: MapLevel;
}

/** 產業鏈層級區段：level 標題（上游/中游/下游）＋可收合手風琴，內含各分類直列。 */
export function ChainLevelSection({ level }: ChainLevelSectionProps) {
  const { level: levelName, categories } = level;

  return (
    <details open className="rounded-xl border border-border-line bg-bg">
      {/* summary 為標題列：層級名稱 ＋ M 類 pill */}
      <summary className="flex cursor-pointer items-center justify-between gap-2 px-4 py-3 select-none">
        <span className="text-lg font-bold text-text-main">{levelName}</span>
        <span className="rounded-full border border-border-line bg-surface-2 px-2.5 py-0.5 text-xs text-text-dim">
          {categories.length} 類
        </span>
      </summary>

      {/* 分類直列 */}
      <div className="flex flex-col gap-3 px-4 pb-4">
        {categories.map((category) => (
          <CategoryBlock key={category.name} category={category} />
        ))}
      </div>
    </details>
  );
}
