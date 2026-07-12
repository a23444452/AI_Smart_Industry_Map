import { useState } from "react";
import { MODES, type AnalysisMode } from "../../api/ai";

interface TriggerPanelProps {
  /** 送出時呼叫（ticker 已 trim、mode 為三值之一）。 */
  onSubmit: (ticker: string, mode: AnalysisMode) => void;
  /** 是否分析進行中（觸發 mutation pending）：輸入與按鈕 disabled。 */
  isPending: boolean;
  /** 後端錯誤訊息（如 409 衝突）；null 不顯示。 */
  errorDetail: string | null;
}

/**
 * 觸發分析面板：股票代號輸入＋模式下拉（三值）＋送出。ticker trim 後為空則不送出；
 * 進行中時整體 disabled；帶後端錯誤訊息（如 409「分析進行中」）時於面板顯示。
 */
export function TriggerPanel({ onSubmit, isPending, errorDetail }: TriggerPanelProps) {
  const [ticker, setTicker] = useState("");
  const [mode, setMode] = useState<AnalysisMode>(MODES[0]);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = ticker.trim();
    if (!trimmed || isPending) return;
    onSubmit(trimmed, mode);
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="rounded-xl border border-border-line bg-surface p-5"
    >
      <h2 className="text-sm font-semibold text-text-main">觸發 AI 分析</h2>
      <div className="mt-4 flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1">
          <span className="text-xs text-text-dim">股票代號</span>
          <input
            type="text"
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
            disabled={isPending}
            placeholder="例如 2330"
            aria-label="股票代號"
            className="w-40 rounded-lg border border-border-line bg-surface px-3 py-2 text-sm text-text-main placeholder:text-text-dim focus:border-accent focus:outline-none disabled:opacity-50"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-text-dim">分析模式</span>
          <select
            value={mode}
            onChange={(e) => setMode(e.target.value as AnalysisMode)}
            disabled={isPending}
            aria-label="分析模式"
            className="rounded-lg border border-border-line bg-surface px-3 py-2 text-sm text-text-main focus:border-accent focus:outline-none disabled:opacity-50"
          >
            {MODES.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </label>
        <button
          type="submit"
          disabled={isPending}
          className="rounded-lg bg-accent px-4 py-2 text-sm text-text-main transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isPending ? "分析中…" : "開始分析"}
        </button>
      </div>
      {errorDetail && (
        <p className="mt-3 rounded-lg border border-up/40 bg-up/10 px-3 py-2 text-sm text-up">
          {errorDetail}
        </p>
      )}
    </form>
  );
}
