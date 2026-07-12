import { ASPECTS, type AspectScores } from "../../api/ai";

/** 分數夾至 0-100（防守後端異常值溢出橫條寬度）。 */
function clampPct(n: number): number {
  if (Number.isNaN(n)) return 0;
  return Math.max(0, Math.min(100, n));
}

/**
 * 五面向分數橫條：依 ASPECTS 固定順序渲染五列，每列標籤＋橫條（寬度 = 分數%）＋分數字。
 * - 缺鍵的面向 → 0 寬 + 「--」
 * - scores 為 null（分析尚未完成）→ 五列皆佔位（0 寬、分數 --）
 */
export function ScoreBars({ scores }: { scores: AspectScores | null }) {
  return (
    <ul className="space-y-2">
      {ASPECTS.map((aspect) => {
        const raw = scores?.[aspect];
        const has = typeof raw === "number";
        const pct = has ? clampPct(raw) : 0;
        return (
          <li key={aspect} className="flex items-center gap-3">
            <span className="w-14 shrink-0 text-xs text-text-dim">{aspect}</span>
            <div className="h-2 flex-1 overflow-hidden rounded-full bg-surface-2">
              <div
                data-testid={`bar-${aspect}`}
                className="h-full rounded-full bg-accent transition-[width]"
                style={{ width: `${pct}%` }}
              />
            </div>
            <span
              data-testid={`score-${aspect}`}
              className="w-8 shrink-0 text-right text-xs tabular-nums text-text-main"
            >
              {has ? raw : "--"}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
