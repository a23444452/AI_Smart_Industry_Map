import { useEChart } from "./chartsCore";
import { toHoldersOption, type HoldersItem } from "./chartOptions";

interface HoldersLineChartProps {
  items: HoldersItem[];
  /** 高度由外部控制，預設 h-64 */
  className?: string;
}

/** 集保大戶持股比週線 + areaStyle（資料轉換走 toHoldersOption）。 */
export function HoldersLineChart({
  items,
  className = "h-64",
}: HoldersLineChartProps) {
  const ref = useEChart(() => toHoldersOption(items), [items]);
  return <div ref={ref} className={`w-full ${className}`} />;
}

// default export 供 React.lazy 動態載入（把 echarts 從主 bundle 拆出）
export default HoldersLineChart;
