import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useTopicDetail } from "../api/topicDetail";
import { Treemap } from "../charts/Treemap";
import { MetricsCard } from "../components/topic/MetricsCard";
import { ChipSignals } from "../components/topic/ChipSignals";
import { DataFreshness } from "../components/topic/DataFreshness";

const TREEMAP_TABS = [
  { value: "day", label: "單日" },
  { value: "week", label: "單週" },
  { value: "month", label: "單月" },
] as const;

type TreemapPeriod = (typeof TREEMAP_TABS)[number]["value"];

/** 題材總覽頁：描述卡＋關鍵指標＋漲跌熱力圖＋籌碼訊號，含載入／404／錯誤四態。 */
export function TopicDetailPage() {
  const { slug = "" } = useParams();
  const [period, setPeriod] = useState<TreemapPeriod>("day");
  const { data, isLoading, isError, error, refetch } = useTopicDetail(slug);

  if (isLoading) return <DetailSkeleton />;

  if (isError) {
    const is404 = (error?.message ?? "").includes("404");
    return is404 ? <NotFound /> : <ErrorCard onRetry={() => void refetch()} />;
  }

  if (!data) return <NotFound />;

  const { title, description, metrics, verified_at, treemap, chip_signals } =
    data;
  // items 直接引用 query data 的穩定陣列，避免 render 內新建陣列造成整圖重繪。
  const treemapItems = treemap[period];

  return (
    <section className="mx-auto max-w-6xl px-6 py-10">
      <Link
        to="/topics"
        className="text-sm text-text-dim transition-colors hover:text-text-main"
      >
        ← 回題材總覽
      </Link>

      {/* 1. 描述卡 */}
      <div className="mt-4 rounded-xl border border-border-line bg-surface p-6">
        <h1 className="text-3xl font-bold text-text-main">{title}</h1>
        {description !== null && (
          <p className="mt-2 text-sm text-text-dim">{description}</p>
        )}
        <div className="mt-4 flex flex-wrap gap-2">
          {metrics.cagr !== undefined && (
            <Badge label={`CAGR ${metrics.cagr}`} />
          )}
          {metrics.market_size !== undefined && (
            <Badge label={`市場規模 ${metrics.market_size}`} />
          )}
        </div>
        {verified_at !== null && (
          <p className="mt-3 text-xs text-text-dim">核實於 {verified_at}</p>
        )}
      </div>

      {/* 2. 總覽／產業鏈 toggle（產業鏈切片 4 才實作） */}
      <div className="mt-6 flex gap-1 border-b border-border-line">
        <button
          type="button"
          aria-pressed="true"
          className="border-b-2 border-accent px-4 py-2 text-sm text-text-main"
        >
          總覽
        </button>
        <button
          type="button"
          disabled
          title="切片 4 實作"
          className="cursor-not-allowed border-b-2 border-transparent px-4 py-2 text-sm text-text-dim opacity-50"
        >
          產業鏈
        </button>
      </div>

      {/* 3. 關鍵指標 */}
      <div className="mt-6">
        <MetricsCard metrics={metrics} />
      </div>

      {/* 4. 漲跌熱力圖 */}
      <div className="mt-6 rounded-xl border border-border-line bg-surface p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-sm font-medium text-text-main">
              產業漲跌熱力圖
            </h2>
            <p className="mt-0.5 text-xs text-text-dim">
              依漲跌幅絕對值決定區塊大小
            </p>
          </div>
          <div className="flex gap-1">
            {TREEMAP_TABS.map((tab) => (
              <button
                key={tab.value}
                type="button"
                aria-pressed={period === tab.value}
                onClick={() => setPeriod(tab.value)}
                className={[
                  "rounded-lg px-3 py-1.5 text-xs transition-colors",
                  period === tab.value
                    ? "bg-accent text-text-main"
                    : "bg-surface-2 text-text-dim hover:text-text-main",
                ].join(" ")}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>
        <Treemap items={treemapItems} className="mt-4 h-96" />
        <div className="mt-2 flex justify-end">
          <DataFreshness lastSuccessAt={data.quotes_updated_at} />
        </div>
      </div>

      {/* 5. 籌碼訊號 */}
      <div className="mt-6">
        <ChipSignals data={chip_signals} />
        {chip_signals.updated_at !== null && (
          <p className="mt-2 text-right text-xs text-text-dim">
            籌碼資料截至 {chip_signals.updated_at}
          </p>
        )}
      </div>
    </section>
  );
}

function Badge({ label }: { label: string }) {
  return (
    <span className="rounded-full border border-border-line bg-surface-2 px-3 py-1 text-xs text-text-dim">
      {label}
    </span>
  );
}

function DetailSkeleton() {
  return (
    <section className="mx-auto max-w-6xl px-6 py-10">
      <div className="h-32 animate-pulse rounded-xl border border-border-line bg-surface" />
      <div className="mt-6 h-96 animate-pulse rounded-xl border border-border-line bg-surface" />
    </section>
  );
}

function NotFound() {
  return (
    <section className="mx-auto max-w-6xl px-6 py-20 text-center">
      <p className="text-lg font-semibold text-text-main">找不到此題材</p>
      <Link
        to="/topics"
        className="mt-4 inline-block rounded-lg bg-accent px-4 py-2 text-sm text-text-main transition-opacity hover:opacity-90"
      >
        回題材總覽
      </Link>
    </section>
  );
}

function ErrorCard({ onRetry }: { onRetry: () => void }) {
  return (
    <section className="mx-auto max-w-6xl px-6 py-20 text-center">
      <p className="text-sm text-text-dim">題材載入失敗，請稍後再試。</p>
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
