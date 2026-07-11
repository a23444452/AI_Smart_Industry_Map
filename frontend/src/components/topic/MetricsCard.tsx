// 已知 metrics key 的中文 label 映射；未知 key 於渲染時原樣顯示。
const LABELS: Record<string, string> = {
  cagr: "CAGR",
  market_size: "市場規模",
  tech_core: "技術核心",
  main_spec: "主力規格",
  commercial_node: "商轉節點",
  barrier: "產業門檻",
};

interface MetricsCardProps {
  metrics: Record<string, string>;
}

/** 題材關鍵指標卡：以 label 映射表呈現 metrics 的 key/value（未知 key 原樣）。 */
export function MetricsCard({ metrics }: MetricsCardProps) {
  const entries = Object.entries(metrics);
  return (
    <div className="rounded-xl border border-border-line bg-surface p-5">
      <h2 className="mb-4 text-sm font-medium text-text-dim">關鍵指標</h2>
      <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {entries.map(([key, value]) => (
          <div key={key} className="flex flex-col gap-1">
            <dt className="text-xs text-text-dim">{LABELS[key] ?? key}</dt>
            <dd className="text-sm font-semibold text-text-main">{value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
