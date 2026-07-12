/**
 * ECharts 共用核心：集中註冊、共用深色樣式常數、與 init/dispose/resize hook。
 *
 * 所有圖表元件（Treemap／KLine／PerRiver／InstitutionalBars／HoldersLine）皆從此
 * 匯入，確保只註冊一次 echarts 模組、共用同一份深色軸樣式，並共用 useEChart 生命
 * 週期邏輯（避免每個元件各自重複 init/dispose/ResizeObserver）。
 */
import { useEffect, useRef, type RefObject } from "react";
import * as echarts from "echarts/core";
import {
  TreemapChart,
  CandlestickChart,
  LineChart,
  BarChart,
} from "echarts/charts";
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { EChartsType, EChartsCoreOption } from "echarts/core";
import { CHART_SURFACE, CHART_BORDER, CHART_TEXT } from "./theme";

// 集中註冊：所有本專案圖表所需的 series 型別、元件與 canvas renderer。
echarts.use([
  TreemapChart,
  CandlestickChart,
  LineChart,
  BarChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
  CanvasRenderer,
]);

// ── 共用深色樣式常數（供純函式建構 option 時套用）─────────────────────────
/** 軸線／刻度線色（分隔線色，較暗） */
export const AXIS_LINE_STYLE = { lineStyle: { color: CHART_BORDER } } as const;
/** 軸文字色（主文字降一階的可讀灰藍） */
export const AXIS_LABEL_STYLE = { color: "#8a94ad" } as const;
/** 分隔線（水平網格線）色，虛線低調 */
export const SPLIT_LINE_STYLE = {
  lineStyle: { color: CHART_BORDER, type: "dashed" as const },
} as const;
/** tooltip 深色底樣式（底色／邊框／文字皆取 theme） */
export const TOOLTIP_STYLE = {
  backgroundColor: CHART_SURFACE,
  borderColor: CHART_BORDER,
  borderWidth: 1,
  textStyle: { color: CHART_TEXT },
} as const;

/**
 * ECharts 生命週期 hook：init 一次 + dispose cleanup + ResizeObserver + setOption。
 *
 * @param optionFactory 建構 ECharts option 的工廠函式（於 deps 變動時重新呼叫）。
 * @param deps          option 依賴（如 [items]）；變動時以 notMerge 重設 option。
 * @returns 綁定到容器 div 的 ref。
 */
export function useEChart(
  optionFactory: () => EChartsCoreOption,
  deps: React.DependencyList,
): RefObject<HTMLDivElement | null> {
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

  // deps 變更時更新 option
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    chart.setOption(optionFactory(), { notMerge: true });
    // optionFactory 於每次 render 重建（閉包捕捉最新 deps），故僅依 deps 觸發。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return containerRef;
}
