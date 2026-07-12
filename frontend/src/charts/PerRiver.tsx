import { useEChart } from "./chartsCore";
import { toPerRiverOption, type PerRiverItem } from "./chartOptions";

interface PerRiverChartProps {
  items: PerRiverItem[];
  /** 高度由外部控制，預設 h-80 */
  className?: string;
}

/** PER 河流圖：close 折線 + 五條分位帶（資料轉換走 toPerRiverOption）。 */
export function PerRiverChart({ items, className = "h-80" }: PerRiverChartProps) {
  const ref = useEChart(() => toPerRiverOption(items), [items]);
  return <div ref={ref} className={`w-full ${className}`} />;
}

// default export 供 React.lazy 動態載入（把 echarts 從主 bundle 拆出）
export default PerRiverChart;
