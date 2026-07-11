import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { TreemapChart } from "echarts/charts";
import { TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { EChartsType } from "echarts/core";
import { toTreemapData, type TreemapInput } from "./toTreemapData";

echarts.use([TreemapChart, TooltipComponent, CanvasRenderer]);

interface TreemapProps {
  items: TreemapInput[];
  /** 高度由外部控制，預設 h-80 */
  className?: string;
}

// 深色底邊框，與頁面背景 --color-bg 一致，讓色塊之間有分隔感
const BORDER_COLOR = "#0b1220";

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function buildOption(items: TreemapInput[]): echarts.EChartsCoreOption {
  const data = toTreemapData(items);
  return {
    tooltip: {
      backgroundColor: "#111a2e",
      borderColor: "#24304d",
      borderWidth: 1,
      textStyle: { color: "#e6ebf5" },
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
        itemStyle: {
          borderColor: BORDER_COLOR,
          borderWidth: 2,
          gapWidth: 2,
        },
        data,
      },
    ],
  };
}

export function Treemap({ items, className = "h-80" }: TreemapProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<EChartsType | null>(null);

  // init 一次 + dispose cleanup + ResizeObserver
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const chart = echarts.init(el, undefined, { renderer: "canvas" });
    chartRef.current = chart;

    const observer = new ResizeObserver(() => {
      chart.resize();
    });
    observer.observe(el);

    return () => {
      observer.disconnect();
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  // items 變更時更新 option
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    chart.setOption(buildOption(items), { notMerge: true });
  }, [items]);

  return <div ref={containerRef} className={`w-full ${className}`} />;
}
