import { useDaily } from "../api/daily";
import { IndexCards } from "../components/daily/IndexCards";
import { MarketFlowsTable } from "../components/daily/MarketFlowsTable";
import { MarginTable } from "../components/daily/MarginTable";
import { MoversRanking } from "../components/daily/MoversRanking";
import { MopsTimeline } from "../components/daily/MopsTimeline";
import { DataFreshness } from "../components/topic/DataFreshness";

/** 每日焦點頁：指數卡→法人／資券兩欄→漲跌榜→重大訊息；含載入／錯誤／空／正常四態。 */
export function DailyPage() {
  const { data, isLoading, isError, refetch } = useDaily();

  if (isLoading) return <DailySkeleton />;
  if (isError) return <ErrorCard onRetry={() => void refetch()} />;
  if (!data) return <EmptyCard />;

  const { indices, market_flows, margin, movers, announcements_dates } = data;
  const isEmpty =
    indices.length === 0 &&
    market_flows.rows.length === 0 &&
    margin.rows.length === 0 &&
    movers.day.length === 0 &&
    announcements_dates.length === 0;
  if (isEmpty) return <EmptyCard />;

  // 頁尾資料時效以第一張指數卡的 fetched_at 為準（跑馬燈為即時性最高的來源）。
  const fetchedAt = indices[0]?.fetched_at ?? null;

  return (
    <section className="mx-auto max-w-6xl px-6 py-10">
      <h1 className="text-2xl font-bold text-text-main">每日焦點</h1>

      <div className="mt-6">
        <IndexCards indices={indices} />
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        <MarketFlowsTable data={market_flows} />
        <MarginTable data={margin} />
      </div>

      <div className="mt-6">
        <MoversRanking movers={movers} />
      </div>

      <div className="mt-6">
        <MopsTimeline dates={announcements_dates} />
      </div>

      <div className="mt-6 flex justify-end">
        <DataFreshness lastSuccessAt={fetchedAt} />
      </div>
    </section>
  );
}

function DailySkeleton() {
  return (
    <section className="mx-auto max-w-6xl px-6 py-10">
      <div className="h-8 w-40 animate-pulse rounded bg-surface" />
      <div className="mt-6 h-24 animate-pulse rounded-xl border border-border-line bg-surface" />
      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        <div className="h-56 animate-pulse rounded-xl border border-border-line bg-surface" />
        <div className="h-56 animate-pulse rounded-xl border border-border-line bg-surface" />
      </div>
      <div className="mt-6 h-72 animate-pulse rounded-xl border border-border-line bg-surface" />
    </section>
  );
}

function EmptyCard() {
  return (
    <section className="mx-auto max-w-6xl px-6 py-20 text-center">
      <p className="text-lg font-semibold text-text-main">每日焦點</p>
      <p className="mt-2 text-sm text-text-dim">暫無資料，請稍後再來查看。</p>
    </section>
  );
}

function ErrorCard({ onRetry }: { onRetry: () => void }) {
  return (
    <section className="mx-auto max-w-6xl px-6 py-20 text-center">
      <p className="text-sm text-text-dim">每日焦點載入失敗，請稍後再試。</p>
      <button
        type="button"
        onClick={onRetry}
        className="mt-4 rounded-lg bg-accent px-4 py-2 text-sm text-text-main transition-opacity hover:opacity-90"
      >
        重試
      </button>
    </section>
  );
}
