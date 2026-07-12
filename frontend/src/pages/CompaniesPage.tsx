import { useEffect, useState } from "react";
import { useCompanies } from "../api/companies";
import { CompanyTable } from "../components/company/CompanyTable";

const PAGE_SIZE = 20;
const SEARCH_DEBOUNCE_MS = 300;

/**
 * 公司資料庫頁：搜尋框（debounce 300ms）＋題材下拉篩選＋公司清單表＋分頁。
 * 含載入／錯誤／空／正常四態；搜尋或改題材時頁碼重置為 1。
 */
export function CompaniesPage() {
  const [queryInput, setQueryInput] = useState("");
  const [query, setQuery] = useState("");
  const [topic, setTopic] = useState("");
  const [page, setPage] = useState(1);

  // 搜尋 debounce：輸入停止 300ms 後才更新查詢字串並回到第 1 頁，避免逐字打字狂發請求。
  useEffect(() => {
    const timer = setTimeout(() => {
      setQuery(queryInput);
      setPage(1);
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [queryInput]);

  const { data, isLoading, isError, refetch, isPlaceholderData } = useCompanies(
    query,
    topic,
    page,
  );

  // topics_facets 恆為全部 topics（後端保證不隨篩選變動）；沿用前次資料避免下拉閃爍。
  const facets = data?.topics_facets ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / (data?.page_size ?? PAGE_SIZE)));

  function onTopicChange(e: React.ChangeEvent<HTMLSelectElement>) {
    setTopic(e.target.value);
    setPage(1);
  }

  return (
    <section className="mx-auto max-w-6xl px-6 py-10">
      <h1 className="text-2xl font-bold text-text-main">公司資料庫</h1>

      {/* 搜尋＋題材篩選 */}
      <div className="mt-6 flex flex-wrap gap-3">
        <input
          type="search"
          value={queryInput}
          onChange={(e) => setQueryInput(e.target.value)}
          placeholder="搜尋代號或名稱"
          aria-label="搜尋代號或名稱"
          className="flex-1 min-w-[16rem] rounded-lg border border-border-line bg-surface px-3 py-2 text-sm text-text-main placeholder:text-text-dim focus:border-accent focus:outline-none"
        />
        <select
          value={topic}
          onChange={onTopicChange}
          aria-label="題材篩選"
          className="rounded-lg border border-border-line bg-surface px-3 py-2 text-sm text-text-main focus:border-accent focus:outline-none"
        >
          <option value="">全部題材</option>
          {facets.map((f) => (
            <option key={f.slug} value={f.slug}>
              {f.title}
            </option>
          ))}
        </select>
      </div>

      {/* 清單區：四態 */}
      <div
        className={`mt-6 ${isPlaceholderData ? "opacity-60 transition-opacity" : ""}`}
      >
        {isLoading ? (
          <TableSkeleton />
        ) : isError ? (
          <ErrorCard onRetry={() => void refetch()} />
        ) : (
          <CompanyTable items={data?.items ?? []} />
        )}
      </div>

      {/* 分頁（有資料且多於一頁時顯示） */}
      {!isLoading && !isError && total > 0 && (
        <div className="mt-4 flex items-center justify-between">
          <p className="text-xs text-text-dim tabular-nums">
            第 {page} 頁·共 {total} 筆
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="rounded-lg border border-border-line bg-surface px-3 py-1.5 text-xs text-text-main transition-colors hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-40"
            >
              上一頁
            </button>
            <button
              type="button"
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
              className="rounded-lg border border-border-line bg-surface px-3 py-1.5 text-xs text-text-main transition-colors hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-40"
            >
              下一頁
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

function TableSkeleton() {
  return (
    <div className="space-y-2">
      {Array.from({ length: 8 }).map((_, i) => (
        <div
          key={i}
          className="h-12 animate-pulse rounded-lg border border-border-line bg-surface"
        />
      ))}
    </div>
  );
}

function ErrorCard({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="rounded-xl border border-border-line bg-surface p-8 text-center">
      <p className="text-sm text-text-dim">公司清單載入失敗，請稍後再試。</p>
      <button
        type="button"
        onClick={onRetry}
        className="mt-4 rounded-lg bg-accent px-4 py-2 text-sm text-text-main transition-opacity hover:opacity-90"
      >
        重試
      </button>
    </div>
  );
}
