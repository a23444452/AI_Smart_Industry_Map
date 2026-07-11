import { useState } from "react";
import { useTopics, type Market } from "../api/topics";
import { TopicCard } from "../components/topics/TopicCard";
import { RankFocusCards } from "../components/topics/RankFocusCards";

// 市場五分頁設定
const MARKET_TABS: { value: Market; label: string }[] = [
  { value: "tw", label: "台股" },
  { value: "us", label: "美股" },
  { value: "jp", label: "日股" },
  { value: "chain", label: "產業鏈" },
  { value: "etf", label: "ETF" },
];

/** 題材總覽頁：排行焦點＋市場分頁＋題材卡片 grid，含載入／錯誤／空狀態。 */
export function TopicsPage() {
  const [market, setMarket] = useState<Market>("tw");
  const [direction, setDirection] = useState<"up" | "down">("up");
  const { data, isLoading, isError, refetch } = useTopics(market, direction);

  return (
    <section className="mx-auto max-w-6xl px-6 py-10">
      <RankFocusCards
        rank={data?.rank ?? []}
        direction={direction}
        onDirectionChange={setDirection}
      />

      {/* 市場五分頁：active 底部 accent 線 */}
      <div className="mb-6 flex gap-1 border-b border-border-line">
        {MARKET_TABS.map((tab) => (
          <button
            key={tab.value}
            type="button"
            onClick={() => setMarket(tab.value)}
            className={[
              "border-b-2 px-4 py-2 text-sm transition-colors",
              market === tab.value
                ? "border-accent text-text-main"
                : "border-transparent text-text-dim hover:text-text-main",
            ].join(" ")}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* 題材卡片 grid（依狀態切換） */}
      {isLoading ? (
        <TopicsSkeleton />
      ) : isError ? (
        <ErrorCard onRetry={() => void refetch()} />
      ) : (data?.topics.length ?? 0) === 0 ? (
        <div className="rounded-xl border border-border-line bg-surface p-8 text-center text-sm text-text-dim">
          此分類暫無題材
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {data?.topics.map((topic) => (
            <TopicCard key={topic.slug} topic={topic} />
          ))}
        </div>
      )}
    </section>
  );
}

/** 載入中骨架卡（pulse 動畫） */
function TopicsSkeleton() {
  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      {Array.from({ length: 6 }).map((_, i) => (
        <div
          key={i}
          className="h-40 animate-pulse rounded-xl border border-border-line bg-surface"
        />
      ))}
    </div>
  );
}

/** 錯誤卡＋重試按鈕 */
function ErrorCard({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="rounded-xl border border-border-line bg-surface p-8 text-center">
      <p className="text-sm text-text-dim">題材載入失敗，請稍後再試。</p>
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
