import type { ChipSignalsData } from "../../api/topicDetail";

interface ChipSignalsProps {
  data: ChipSignalsData;
}

/** 單一法人買超統計列：label ＋「買超家數/總數」（值為 null 時顯示 —）。 */
function SignalRow({
  label,
  buy,
  total,
}: {
  label: string;
  buy: number | null;
  total: number;
}) {
  return (
    <div className="flex items-baseline justify-between rounded-lg bg-surface-2 px-3 py-2.5">
      <span className="text-sm text-text-dim">{label}</span>
      <span className="text-sm font-semibold tabular-nums text-text-main">
        {buy === null ? "—" : `${buy}/${total}`}
      </span>
    </div>
  );
}

/** 籌碼訊號卡：近 N 個交易日內外資／投信／大戶（自營）買超家數統計。 */
export function ChipSignals({ data }: ChipSignalsProps) {
  const { window_days, total, foreign_buy, trust_buy, major_buy } = data;
  return (
    <div className="rounded-xl border border-border-line bg-surface p-5">
      <h2 className="text-sm font-medium text-text-main">籌碼訊號</h2>
      <p className="mt-0.5 text-xs text-text-dim">
        近 {window_days} 個交易日買超家數
      </p>
      <div className="mt-4 grid gap-2">
        <SignalRow label="外資" buy={foreign_buy} total={total} />
        <SignalRow label="投信" buy={trust_buy} total={total} />
        <SignalRow label="大戶" buy={major_buy} total={total} />
      </div>
    </div>
  );
}
