import { ASPECTS, type AnalysisStatus, type AspectScores } from "../../api/ai";
import { formatDateTaipei } from "../../lib/format";
import { ScoreBars } from "./ScoreBars";

/**
 * AnalysisCard 的資料契約——同時涵蓋 AnalysisDetail（單筆輪詢）與 LeaderboardItem
 * （榜單列）。status/summary/reasons/error 為單筆分析才有的欄位（榜單省略，視為 done）。
 */
export interface AnalysisCardData {
  ticker: string;
  name: string | null;
  mode: string;
  scores: AspectScores | null;
  total: number | null;
  model: string | null;
  created_at: string | null;
  status?: AnalysisStatus;
  summary?: string | null;
  reasons?: Record<string, string[]> | null;
  error?: string | null;
  rank?: number;
}

/** mock provider 的 model 標記（後端 factory.provider_label 回傳 "mock"）。 */
const MOCK_MODEL = "mock";

/**
 * 單筆分析卡：ticker/name、mode chip、五面向分數條、total 大字、綜合結論、
 * 台北時間；model 為 mock 時掛「模擬分析」badge。status 為 failed 時改顯示
 * error 訊息（不渲染分數條）。
 */
export function AnalysisCard({ data }: { data: AnalysisCardData }) {
  const isFailed = data.status === "failed";
  const isMock = data.model === MOCK_MODEL;
  const dateLabel = formatDateTaipei(data.created_at);

  return (
    <article className="rounded-xl border border-border-line bg-surface p-5">
      {/* 頭部：代號／名稱／模式／模擬 badge／排名 */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          {data.rank != null && (
            <span className="text-sm font-semibold tabular-nums text-text-dim">
              #{data.rank}
            </span>
          )}
          <span className="font-semibold tabular-nums text-text-main">
            {data.ticker}
          </span>
          {data.name && (
            <span className="text-text-main">{data.name}</span>
          )}
          <span className="rounded-full bg-surface-2 px-2 py-0.5 text-xs text-text-dim">
            {data.mode}
          </span>
          {isMock && (
            <span className="rounded-full border border-border-line px-2 py-0.5 text-xs text-text-dim">
              模擬分析
            </span>
          )}
        </div>
        {!isFailed && data.total != null && (
          <div className="shrink-0 text-right">
            <div className="text-2xl font-bold tabular-nums text-text-main">
              {data.total}
            </div>
            <div className="text-[10px] text-text-dim">綜合評分</div>
          </div>
        )}
      </div>

      {/* 主體：失敗態顯示 error；否則五面向分數條＋結論 */}
      {isFailed ? (
        <p className="mt-4 rounded-lg border border-up/40 bg-up/10 px-3 py-2 text-sm text-up">
          {data.error ?? "分析失敗，請稍後重試。"}
        </p>
      ) : (
        <>
          <div className="mt-4">
            <ScoreBars scores={data.scores} />
          </div>
          {data.summary && (
            <p className="mt-3 text-sm leading-relaxed text-text-dim">
              {data.summary}
            </p>
          )}
          {data.reasons && (
            <details className="mt-3 rounded-lg border border-border-line px-3 py-2">
              <summary className="cursor-pointer select-none text-xs text-text-dim hover:text-text-main">
                查看各面向理由
              </summary>
              <dl className="mt-2 space-y-3">
                {ASPECTS.map((aspect) => {
                  const lines = data.reasons?.[aspect];
                  if (!lines?.length) return null;
                  return (
                    <div key={aspect}>
                      <dt className="text-xs font-semibold text-text-main">
                        {aspect}
                      </dt>
                      <dd className="mt-1">
                        <ul className="space-y-0.5">
                          {lines.map((line, i) => (
                            <li
                              key={i}
                              className="text-xs leading-relaxed text-text-dim"
                            >
                              {line}
                            </li>
                          ))}
                        </ul>
                      </dd>
                    </div>
                  );
                })}
              </dl>
            </details>
          )}
        </>
      )}

      {dateLabel && (
        <p className="mt-3 text-right text-[10px] text-text-dim">
          分析於 <time dateTime={data.created_at ?? undefined}>{dateLabel}</time>
        </p>
      )}
    </article>
  );
}
