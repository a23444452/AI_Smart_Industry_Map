import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ApiError } from "../api/client";
import {
  MODES,
  shouldRefreshLeaderboard,
  useAnalysis,
  useLeaderboard,
  useTriggerAnalysis,
  type AnalysisMode,
  type AnalysisStatus,
  type LeaderboardSort,
} from "../api/ai";
import { AnalysisCard } from "../components/ai/AnalysisCard";
import { TriggerPanel } from "../components/ai/TriggerPanel";

/** 榜單模式篩選 chips：全部（null）＋三模式。 */
const MODE_FILTERS: { label: string; value: string | null }[] = [
  { label: "全部", value: null },
  ...MODES.map((m) => ({ label: m, value: m as string })),
];

/**
 * AI 分析頁 `/ai`：
 * 1. TriggerPanel（頂部）觸發分析
 * 2. 進行中/最新觸發的分析卡（輪詢：pending/running spinner、done 顯示卡、
 *    failed 顯示 error、逾時顯示重試提示）
 * 3. 排行榜（強勢/弱勢 toggle＋模式篩選 chips＋AnalysisCard 列，四態）
 * 4. 免責 footer
 */
export function AiPage() {
  const [currentId, setCurrentId] = useState<number | null>(null);
  const [sort, setSort] = useState<LeaderboardSort>("strong");
  const [modeFilter, setModeFilter] = useState<string | null>(null);

  const trigger = useTriggerAnalysis();
  const analysis = useAnalysis(currentId);
  const leaderboard = useLeaderboard(sort, modeFilter);

  // I-1：分析狀態「轉為 done」時 invalidate 排行榜——新完成的分析立即上榜，
  // 不必手動重整。以 ref 記前次狀態，判斷邏輯抽為純函式（shouldRefreshLeaderboard）。
  const queryClient = useQueryClient();
  const status = analysis.data?.status;
  const prevStatusRef = useRef<AnalysisStatus | undefined>(undefined);
  useEffect(() => {
    if (shouldRefreshLeaderboard(prevStatusRef.current, status)) {
      void queryClient.invalidateQueries({ queryKey: ["ai-leaderboard"] });
    }
    prevStatusRef.current = status;
  }, [status, queryClient]);

  function handleSubmit(ticker: string, mode: AnalysisMode) {
    trigger.mutate(
      { ticker, mode },
      { onSuccess: (res) => setCurrentId(res.analysis_id) },
    );
  }

  // 409 等後端錯誤：優先顯示後端訊息（error.detail），否則泛用提示。
  const triggerErrorDetail = trigger.isError
    ? trigger.error instanceof ApiError
      ? (trigger.error.detail ?? "觸發分析失敗，請稍後再試。")
      : "觸發分析失敗，請稍後再試。"
    : null;

  return (
    <section className="mx-auto max-w-6xl px-6 py-10">
      <h1 className="text-2xl font-bold text-text-main">AI 分析</h1>
      <p className="mt-1 text-sm text-text-dim">
        五面向評分（題材／基本／技術／籌碼／新聞）與強弱勢排行。
      </p>

      {/* 1. 觸發面板 */}
      <div className="mt-6">
        <TriggerPanel
          onSubmit={handleSubmit}
          isPending={trigger.isPending}
          errorDetail={triggerErrorDetail}
        />
      </div>

      {/* 2. 進行中／最新觸發的分析 */}
      {currentId != null && (
        <div className="mt-6">
          <h2 className="mb-3 text-sm font-semibold text-text-dim">最新分析</h2>
          <CurrentAnalysis analysis={analysis} />
        </div>
      )}

      {/* 3. 排行榜 */}
      <div className="mt-10">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg font-bold text-text-main">評分排行榜</h2>
          <div className="inline-flex rounded-lg border border-border-line p-0.5">
            {(
              [
                { key: "strong", label: "強勢" },
                { key: "weak", label: "弱勢" },
              ] as const
            ).map((opt) => (
              <button
                key={opt.key}
                type="button"
                onClick={() => setSort(opt.key)}
                className={[
                  "rounded-md px-3 py-1 text-sm transition-colors",
                  sort === opt.key
                    ? "bg-accent text-text-main"
                    : "text-text-dim hover:text-text-main",
                ].join(" ")}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        {/* 模式篩選 chips */}
        <div className="mt-4 flex flex-wrap gap-2">
          {MODE_FILTERS.map((f) => (
            <button
              key={f.label}
              type="button"
              onClick={() => setModeFilter(f.value)}
              className={[
                "rounded-full px-3 py-1 text-xs transition-colors",
                modeFilter === f.value
                  ? "bg-accent text-text-main"
                  : "border border-border-line text-text-dim hover:text-text-main",
              ].join(" ")}
            >
              {f.label}
            </button>
          ))}
        </div>

        {/* 榜單四態 */}
        <div className="mt-6">
          {leaderboard.isLoading ? (
            <ListSkeleton />
          ) : leaderboard.isError ? (
            <StateCard
              text="排行榜載入失敗，請稍後再試。"
              onRetry={() => void leaderboard.refetch()}
            />
          ) : (leaderboard.data?.items.length ?? 0) === 0 ? (
            <StateCard text="尚無分析資料，於上方觸發第一筆分析吧。" />
          ) : (
            <ul className="grid gap-4 md:grid-cols-2">
              {leaderboard.data?.items.map((item) => (
                <li key={`${item.ticker}-${item.mode}`}>
                  <AnalysisCard data={item} />
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <footer className="mt-10 border-t border-border-line pt-4 text-center text-xs text-text-dim">
        AI 評分僅供參考，不構成投資建議
      </footer>
    </section>
  );
}

/** 最新分析區塊的四態渲染（載入／逾時／進行中／完成或失敗）。 */
function CurrentAnalysis({
  analysis,
}: {
  analysis: ReturnType<typeof useAnalysis>;
}) {
  if (analysis.isLoading) return <Spinner text="讀取分析中…" />;

  if (analysis.isError) {
    return (
      <StateCard
        text="讀取分析失敗，請稍後再試。"
        onRetry={() => void analysis.refetch()}
      />
    );
  }

  const data = analysis.data;
  if (!data) return null;

  // 逾時安全網：進行中但已超過輪詢上限（輪詢已停）→ 提示重試。
  // 重試走 restart()：重置輪詢起始 timestamp 再 refetch，恢復 2 秒輪詢。
  if (analysis.timedOut) {
    return <StateCard text="分析逾時，請稍後重試" onRetry={analysis.restart} />;
  }

  if (data.status === "pending" || data.status === "running") {
    return <Spinner text={`分析中…（${data.ticker}）`} />;
  }

  // done / failed 皆由 AnalysisCard 處理（failed 顯示 error）。
  return <AnalysisCard data={data} />;
}

function Spinner({ text }: { text: string }) {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-border-line bg-surface p-6">
      <span
        aria-hidden="true"
        className="h-5 w-5 animate-spin rounded-full border-2 border-border-line border-t-accent"
      />
      <span className="text-sm text-text-dim">{text}</span>
    </div>
  );
}

function StateCard({ text, onRetry }: { text: string; onRetry?: () => void }) {
  return (
    <div className="rounded-xl border border-border-line bg-surface p-8 text-center">
      <p className="text-sm text-text-dim">{text}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-4 rounded-lg bg-accent px-4 py-2 text-sm text-text-main transition-opacity hover:opacity-90"
        >
          重試
        </button>
      )}
    </div>
  );
}

function ListSkeleton() {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {Array.from({ length: 4 }).map((_, i) => (
        <div
          key={i}
          className="h-40 animate-pulse rounded-xl border border-border-line bg-surface"
        />
      ))}
    </div>
  );
}
