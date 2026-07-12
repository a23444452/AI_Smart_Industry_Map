import type { EChartsCoreOption } from "echarts/core";
import { useEChart } from "./chartsCore";
import { toTreemapData, type TreemapInput } from "./toTreemapData";
import { CHART_BG, CHART_SURFACE, CHART_BORDER, CHART_TEXT } from "./theme";

interface TreemapProps {
  items: TreemapInput[];
  /** 高度由外部控制，預設 h-80 */
  className?: string;
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function buildOption(items: TreemapInput[]): EChartsCoreOption {
  const data = toTreemapData(items);
  return {
    tooltip: {
      backgroundColor: CHART_SURFACE,
      borderColor: CHART_BORDER,
      borderWidth: 1,
      textStyle: { color: CHART_TEXT },
      // node.name 內含「名稱\n{formatPct}」——tooltip 拆兩行顯示 name＋漲跌
      formatter: (info: unknown) => {
        const p = info as { name?: string };
        const [name = "", pct = ""] = (p.name ?? "").split("\n");
        return `${escapeHtml(name)}<br/>${escapeHtml(pct)}`;
      },
    },
    series: [
      {
        type: "treemap",
        roam: false,
        nodeClick: false,
        breadcrumb: { show: false },
        width: "100%",
        height: "100%",
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        label: {
          show: true,
          color: "#ffffff",
          fontSize: 12,
          lineHeight: 16,
          overflow: "truncate",
        },
        // 色塊分隔邊框用頁面底色，與 --color-bg 一致，讓色塊之間有分隔感
        itemStyle: {
          borderColor: CHART_BG,
          borderWidth: 2,
          gapWidth: 2,
        },
        data,
      },
    ],
  };
}

export function Treemap({ items, className = "h-80" }: TreemapProps) {
  // init/dispose/ResizeObserver/setOption 邏輯集中於 chartsCore.useEChart。
  const containerRef = useEChart(() => buildOption(items), [items]);
  return <div ref={containerRef} className={`w-full ${className}`} />;
}

// default export 供 React.lazy 動態載入（把 echarts 從主 bundle 拆出）
export default Treemap;
