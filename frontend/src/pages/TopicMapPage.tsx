import { Link, useParams } from "react-router-dom";
import { ApiError } from "../api/client";
import { useTopicMap } from "../api/topicMap";
import { ChainLevelSection } from "../components/map/ChainLevelSection";

/** 產業地圖頁：頂部導覽＋總覽/產業鏈 toggle＋各層級產業鏈區段，含載入／404／錯誤四態。 */
export function TopicMapPage() {
  const { slug = "" } = useParams();
  const { data, isLoading, isError, error, refetch } = useTopicMap(slug);

  if (isLoading) return <MapSkeleton />;

  if (isError) {
    // 以 ApiError.status 判斷 404，不解析 message 字串（slug 含 "404" 時不誤判）。
    const is404 = error instanceof ApiError && error.status === 404;
    return is404 ? <NotFound /> : <ErrorCard onRetry={() => void refetch()} />;
  }

  if (!data) return <NotFound />;

  const { title, levels } = data;

  return (
    <section className="mx-auto max-w-6xl px-6 py-10">
      <Link
        to="/topics"
        className="text-sm text-text-dim transition-colors hover:text-text-main"
      >
        ← 回題材總覽
      </Link>

      {/* 1. 標題＋副標 */}
      <div className="mt-4">
        <h1 className="text-3xl font-bold text-text-main">{title}</h1>
        <p className="mt-1 text-sm text-text-dim">產業內部結構</p>
      </div>

      {/* 2. 總覽／產業鏈 toggle（此頁產業鏈為 active；差異比較尚未實作） */}
      <div className="mt-6 flex gap-1 border-b border-border-line">
        <Link
          to={`/topic/${slug}`}
          className="border-b-2 border-transparent px-4 py-2 text-sm text-text-dim transition-colors hover:text-text-main"
        >
          總覽
        </Link>
        <span
          aria-current="page"
          className="border-b-2 border-accent px-4 py-2 text-sm text-text-main"
        >
          產業鏈
        </span>
        <button
          type="button"
          disabled
          title="尚未實作"
          className="cursor-not-allowed border-b-2 border-transparent px-4 py-2 text-sm text-text-dim opacity-50"
        >
          差異比較
        </button>
      </div>

      {/* 3. 產業鏈層級區段 */}
      <div className="mt-6 flex flex-col gap-4">
        {levels.map((level) => (
          <ChainLevelSection key={level.level} level={level} />
        ))}
      </div>
    </section>
  );
}

function MapSkeleton() {
  return (
    <section className="mx-auto max-w-6xl px-6 py-10">
      <div className="h-10 w-64 animate-pulse rounded-lg bg-surface" />
      <div className="mt-6 h-40 animate-pulse rounded-xl border border-border-line bg-surface" />
      <div className="mt-4 h-40 animate-pulse rounded-xl border border-border-line bg-surface" />
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
      <p className="text-sm text-text-dim">產業地圖載入失敗，請稍後再試。</p>
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
