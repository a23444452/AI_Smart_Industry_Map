import { useEChart } from "./chartsCore";
import { toKLineOption, type KlineItem } from "./chartOptions";

interface KLineChartProps {
  items: KlineItem[];
  /** 高度由外部控制，預設 h-96 */
  className?: string;
}

/** 個股 K 線 + 成交量圖（資料轉換全走 toKLineOption 純函式）。 */
export function KLineChart({ items, className = "h-96" }: KLineChartProps) {
  const ref = useEChart(() => toKLineOption(items), [items]);
  return <div ref={ref} className={`w-full ${className}`} />;
}

// default export 供 React.lazy 動態載入（把 echarts 從主 bundle 拆出）
export default KLineChart;
