import { useEChart } from "./chartsCore";
import { toInstitutionalOption, type InstitutionalItem } from "./chartOptions";

interface InstitutionalBarsChartProps {
  items: InstitutionalItem[];
  /** 高度由外部控制，預設 h-80 */
  className?: string;
}

/** 三大法人買賣超 bar（外資／投信／自營商，資料轉換走 toInstitutionalOption）。 */
export function InstitutionalBarsChart({
  items,
  className = "h-80",
}: InstitutionalBarsChartProps) {
  const ref = useEChart(() => toInstitutionalOption(items), [items]);
  return <div ref={ref} className={`w-full ${className}`} />;
}

// default export 供 React.lazy 動態載入（把 echarts 從主 bundle 拆出）
export default InstitutionalBarsChart;
