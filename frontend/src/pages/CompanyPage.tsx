import { Suspense, lazy, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError } from "../api/client";
import {
  useCompany,
  useCompanyChart,
  type ChartKind,
  type ChartItemMap,
} from "../api/companies";
import { QuoteHeader } from "../components/company/QuoteHeader";
import { DataFreshness } from "../components/topic/DataFreshness";

// echarts 較重，四張圖各自 lazy 拆為動態載入（共享 chartsCore → 單一 echarts chunk），
// 僅在個股頁需要時才載入。
const KLineChart = lazy(() => import("../charts/KLine"));
const PerRiverChart = lazy(() => import("../charts/PerRiver"));
const InstitutionalBarsChart = lazy(() => import("../charts/InstitutionalBars"));
const HoldersLineChart = lazy(() => import("../charts/HoldersLine"));

/** 個股頁：報價抬頭＋四張圖表（K 線／本益比河流／三大法人／大戶持股），含載入／404／錯誤四態。 */
export function CompanyPage() {
  const { ticker = "" } = useParams();
  const { data, isLoading, isError, error, refetch } = useCompany(ticker);

  if (isLoading) return <CompanySkeleton />;

  if (isError) {
    // 以 ApiError.status 判斷 404（ticker 含 "404" 時不誤判）。
    const is404 = error instanceof ApiError && error.status === 404;
    return is404 ? <NotFound /> : <ErrorCard onRetry={() => void refetch()} />;
  }

  if (!data) return <NotFound />;

  return (
    <section className="mx-auto max-w-6xl px-6 py-10">
      <Link
        to="/companies"
        className="text-sm text-text-dim transition-colors hover:text-text-main"
      >
        ← 回公司資料庫
      </Link>

      <div className="mt-4">
        <QuoteHeader company={data} />
      </div>

      <div className="mt-6 space-y-6">
        <ChartSection
          ticker={ticker}
          kind="kline"
          title="K 線圖"
          heightClass="h-96"
          render={(items) => <KLineChart items={items} className="h-96" />}
        />
        <ChartSection
          ticker={ticker}
          kind="per_river"
          title="本益比河流圖"
          heightClass="h-80"
          render={(items) => <PerRiverChart items={items} className="h-80" />}
        />
        <ChartSection
          ticker={ticker}
          kind="institutional"
          title="三大法人買賣超"
          heightClass="h-64"
          render={(items) => (
            <InstitutionalBarsChart items={items} className="h-64" />
          )}
        />
        <ChartSection
          ticker={ticker}
          kind="holders"
          title="大戶持股比例"
          heightClass="h-64"
          render={(items) => <HoldersLineChart items={items} className="h-64" />}
        />
      </div>

      <div className="mt-6 flex justify-end">
        <DataFreshness lastSuccessAt={data.quotes_updated_at} />
      </div>
    </section>
  );
}

/**
 * 單一圖表區塊：標題＋卡片；依 useCompanyChart 狀態切載入骨架／「暫無資料」佔位／
 * lazy 圖表（Suspense skeleton）。render 依 kind 靜態決定對應的圖表元件與 items 型別。
 */
function ChartSection<K extends ChartKind>({
  ticker,
  kind,
  title,
  heightClass,
  render,
}: {
  ticker: string;
  kind: K;
  title: string;
  heightClass: string;
  render: (items: ChartItemMap[K][]) => ReactNode;
}) {
  const { data, isLoading } = useCompanyChart(ticker, kind);
  const items = data?.items ?? [];

  return (
    <div className="rounded-xl border border-border-line bg-surface p-5">
      <h2 className="text-sm font-medium text-text-main">{title}</h2>
      <div className="mt-3">
        {isLoading ? (
          <ChartSkeleton heightClass={heightClass} />
        ) : items.length === 0 ? (
          <div
            className={`flex w-full items-center justify-center rounded-xl border border-dashed border-border-line ${heightClass} text-sm text-text-dim`}
          >
            暫無資料
          </div>
        ) : (
          <Suspense fallback={<ChartSkeleton heightClass={heightClass} />}>
            {render(items)}
          </Suspense>
        )}
      </div>
    </div>
  );
}

function ChartSkeleton({ heightClass }: { heightClass: string }) {
  return (
    <div className={`w-full animate-pulse rounded-xl bg-surface-2 ${heightClass}`} />
  );
}

function CompanySkeleton() {
  return (
    <section className="mx-auto max-w-6xl px-6 py-10">
      <div className="h-40 animate-pulse rounded-xl border border-border-line bg-surface" />
      <div className="mt-6 h-96 animate-pulse rounded-xl border border-border-line bg-surface" />
    </section>
  );
}

function NotFound() {
  return (
    <section className="mx-auto max-w-6xl px-6 py-20 text-center">
      <p className="text-lg font-semibold text-text-main">找不到此公司</p>
      <Link
        to="/companies"
        className="mt-4 inline-block rounded-lg bg-accent px-4 py-2 text-sm text-text-main transition-opacity hover:opacity-90"
      >
        回公司資料庫
      </Link>
    </section>
  );
}

function ErrorCard({ onRetry }: { onRetry: () => void }) {
  return (
    <section className="mx-auto max-w-6xl px-6 py-20 text-center">
      <p className="text-sm text-text-dim">個股資料載入失敗，請稍後再試。</p>
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
