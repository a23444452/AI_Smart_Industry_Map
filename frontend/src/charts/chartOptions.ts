/**
 * 個股圖表純函式：將後端 charts API 的 items 轉為 ECharts option。
 *
 * 全部為無副作用純函式，方便單元測試（元件本身因 jsdom 無 canvas 不測）。
 * 台股慣例：紅漲綠跌（UP_COLORS 紅／DOWN_COLORS 綠）。
 * 後端各欄多為 nullable，故轉換時皆容忍 null（折線以 connectNulls:false 斷線）。
 */
import type { EChartsCoreOption } from "echarts/core";
import { UP_COLORS, DOWN_COLORS } from "./theme";
import {
  AXIS_LINE_STYLE,
  AXIS_LABEL_STYLE,
  SPLIT_LINE_STYLE,
  TOOLTIP_STYLE,
} from "./chartsCore";

// ── 後端 charts API item 型別（對應 companies.py 的回應）────────────────────
export interface KlineItem {
  date: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  volume: number | null;
}

export interface PerRiverItem {
  date: string;
  close: number | null;
  band_p10: number | null;
  band_p25: number | null;
  band_p50: number | null;
  band_p75: number | null;
  band_p90: number | null;
}

export interface InstitutionalItem {
  date: string;
  foreign_net: number | null;
  trust_net: number | null;
  dealer_net: number | null;
}

export interface HoldersItem {
  week: string;
  ratio_400up: number;
}

/** K 線圖預設顯示的最近筆數（dataZoom 視窗）。 */
export const KLINE_RECENT = 60;

/** close ≥ open 視為上漲（紅）；含平盤，與 ECharts candlestick 陽線判定一致。 */
function isUp(open: number | null, close: number | null): boolean {
  return open !== null && close !== null && close >= open;
}

// ── K 線 + 成交量 ──────────────────────────────────────────────────────────
/**
 * K 線（candlestick）+ 成交量副圖。
 * - candlestick data 順序為 ECharts 格式 [open, close, low, high]（非 OHLC！）
 * - 陽線（close≥open）紅 UP_COLORS[1]、陰線綠 DOWN_COLORS[1]
 *   （itemStyle.color=陽線、color0=陰線；邊框同色）
 * - 成交量 bar 逐筆依漲跌著色，與 K 棒同步
 * - dataZoom 預設視窗為最近 KLINE_RECENT(60) 筆
 */
export function toKLineOption(items: KlineItem[]): EChartsCoreOption {
  const dates = items.map((i) => i.date);
  const candle = items.map((i) => [i.open, i.close, i.low, i.high]);
  const volumes = items.map((i) => ({
    value: i.volume,
    itemStyle: { color: isUp(i.open, i.close) ? UP_COLORS[1] : DOWN_COLORS[1] },
  }));

  // dataZoom 起點百分比：>60 筆時只顯示尾端 60 筆，否則全顯示。
  const n = items.length;
  const zoomStart =
    n > KLINE_RECENT ? ((n - KLINE_RECENT) / n) * 100 : 0;

  return {
    tooltip: { ...TOOLTIP_STYLE, trigger: "axis", axisPointer: { type: "cross" } },
    axisPointer: { link: [{ xAxisIndex: "all" }] },
    grid: [
      { left: 56, right: 16, top: 16, height: "58%" },
      { left: 56, right: 16, top: "74%", bottom: 40 },
    ],
    xAxis: [
      {
        type: "category",
        data: dates,
        gridIndex: 0,
        axisLine: AXIS_LINE_STYLE,
        axisLabel: { ...AXIS_LABEL_STYLE, show: false },
        boundaryGap: true,
      },
      {
        type: "category",
        data: dates,
        gridIndex: 1,
        axisLine: AXIS_LINE_STYLE,
        axisLabel: AXIS_LABEL_STYLE,
        boundaryGap: true,
      },
    ],
    yAxis: [
      {
        scale: true,
        gridIndex: 0,
        axisLine: AXIS_LINE_STYLE,
        axisLabel: AXIS_LABEL_STYLE,
        splitLine: SPLIT_LINE_STYLE,
      },
      {
        scale: true,
        gridIndex: 1,
        axisLine: AXIS_LINE_STYLE,
        axisLabel: { ...AXIS_LABEL_STYLE, show: false },
        splitLine: { show: false },
      },
    ],
    dataZoom: [
      { type: "inside", xAxisIndex: [0, 1], start: zoomStart, end: 100 },
      {
        type: "slider",
        xAxisIndex: [0, 1],
        start: zoomStart,
        end: 100,
        bottom: 8,
        height: 16,
      },
    ],
    series: [
      {
        name: "K線",
        type: "candlestick",
        xAxisIndex: 0,
        yAxisIndex: 0,
        data: candle,
        itemStyle: {
          color: UP_COLORS[1],
          color0: DOWN_COLORS[1],
          borderColor: UP_COLORS[1],
          borderColor0: DOWN_COLORS[1],
        },
      },
      {
        name: "成交量",
        type: "bar",
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: volumes,
      },
    ],
  };
}

// ── PER 河流圖 ─────────────────────────────────────────────────────────────
const RIVER_BANDS = [
  { key: "band_p10", name: "P10" },
  { key: "band_p25", name: "P25" },
  { key: "band_p50", name: "P50" },
  { key: "band_p75", name: "P75" },
  { key: "band_p90", name: "P90" },
] as const;

/** close 折線用醒目色（主文字色，浮於半透明藍帶之上）。 */
const CANDLE_LINE = "#e6ebf5";

/**
 * PER 河流圖：close 折線 + 五條分位帶（P10/25/50/75/90）。
 *
 * 帶間填色採「areaStyle 疊層」而非 stack：各帶為獨立 line，帶下方以半透明藍填至軸；
 * 帶越靠中位、opacity 越高，重疊處自然疊出深淺漸層的「河流」感。選疊層而非 stack 是
 * 因後端 band 為 nullable，null 日需斷線（connectNulls:false）——stack 遇 null 會錯位，
 * 獨立 line 疊層則每條各自斷線、互不影響，對 null 穩健。
 */
export function toPerRiverOption(items: PerRiverItem[]): EChartsCoreOption {
  const dates = items.map((i) => i.date);
  const bandSeries = RIVER_BANDS.map((b, idx) => ({
    name: b.name,
    type: "line" as const,
    data: items.map((i) => i[b.key]),
    connectNulls: false,
    showSymbol: false,
    lineStyle: { width: 1, opacity: 0.5, color: "#5b8def" },
    // 疊層填色：中位帶 opacity 最高，向兩端遞減，重疊出漸層。
    areaStyle: { color: "#5b8def", opacity: 0.06 + 0.05 * (2 - Math.abs(2 - idx)) },
  }));

  return {
    tooltip: { ...TOOLTIP_STYLE, trigger: "axis" },
    legend: { textStyle: { color: AXIS_LABEL_STYLE.color }, top: 0 },
    grid: { left: 56, right: 16, top: 32, bottom: 32 },
    xAxis: {
      type: "category",
      data: dates,
      axisLine: AXIS_LINE_STYLE,
      axisLabel: AXIS_LABEL_STYLE,
    },
    yAxis: {
      scale: true,
      axisLine: AXIS_LINE_STYLE,
      axisLabel: AXIS_LABEL_STYLE,
      splitLine: SPLIT_LINE_STYLE,
    },
    series: [
      ...bandSeries,
      {
        name: "收盤",
        type: "line",
        data: items.map((i) => i.close),
        connectNulls: false,
        showSymbol: false,
        lineStyle: { width: 2, color: CANDLE_LINE },
        itemStyle: { color: CANDLE_LINE },
      },
    ],
  };
}

// ── 三大法人買賣超 ─────────────────────────────────────────────────────────
const FLOW_SERIES = [
  { key: "foreign_net", name: "外資" },
  { key: "trust_net", name: "投信" },
  { key: "dealer_net", name: "自營商" },
] as const;

/** 買賣超正紅負綠；0 或 null 以中性灰。 */
function flowColor(v: number | null): string {
  if (v === null || v === 0) return "#3a4358";
  return v > 0 ? UP_COLORS[1] : DOWN_COLORS[1];
}

/**
 * 三大法人買賣超：外資／投信／自營商三系列 bar，正紅負綠、以零為基準軸。
 * 逐筆依 value 正負著色（正紅 UP_COLORS[1]／負綠 DOWN_COLORS[1]／0 或 null 中性）。
 */
export function toInstitutionalOption(
  items: InstitutionalItem[],
): EChartsCoreOption {
  const dates = items.map((i) => i.date);
  const series = FLOW_SERIES.map((s) => ({
    name: s.name,
    type: "bar" as const,
    data: items.map((i) => ({
      value: i[s.key],
      itemStyle: { color: flowColor(i[s.key]) },
    })),
  }));

  return {
    tooltip: { ...TOOLTIP_STYLE, trigger: "axis" },
    legend: { textStyle: { color: AXIS_LABEL_STYLE.color }, top: 0 },
    grid: { left: 64, right: 16, top: 32, bottom: 32 },
    xAxis: {
      type: "category",
      data: dates,
      axisLine: AXIS_LINE_STYLE,
      axisLabel: AXIS_LABEL_STYLE,
    },
    // value 軸含 0；以零為基準軸（正負分居兩側）。
    yAxis: {
      type: "value",
      axisLine: AXIS_LINE_STYLE,
      axisLabel: AXIS_LABEL_STYLE,
      splitLine: SPLIT_LINE_STYLE,
    },
    series,
  };
}

// ── 集保大戶持股比 ─────────────────────────────────────────────────────────
/**
 * 集保大戶（>400 張）持股比週線：單一 line + areaStyle，y 軸為百分比（%）。
 */
export function toHoldersOption(items: HoldersItem[]): EChartsCoreOption {
  return {
    tooltip: {
      ...TOOLTIP_STYLE,
      trigger: "axis",
      valueFormatter: (v: unknown) =>
        typeof v === "number" ? `${v.toFixed(2)}%` : "--",
    },
    grid: { left: 56, right: 16, top: 24, bottom: 32 },
    xAxis: {
      type: "category",
      data: items.map((i) => i.week),
      axisLine: AXIS_LINE_STYLE,
      axisLabel: AXIS_LABEL_STYLE,
    },
    yAxis: {
      type: "value",
      scale: true,
      axisLine: AXIS_LINE_STYLE,
      axisLabel: { ...AXIS_LABEL_STYLE, formatter: "{value}%" },
      splitLine: SPLIT_LINE_STYLE,
    },
    series: [
      {
        name: "大戶持股比",
        type: "line",
        data: items.map((i) => i.ratio_400up),
        showSymbol: false,
        smooth: true,
        lineStyle: { width: 2, color: "#5b8def" },
        itemStyle: { color: "#5b8def" },
        areaStyle: { color: "#5b8def", opacity: 0.18 },
      },
    ],
  };
}
