import { describe, it, expect } from "vitest";
import {
  toKLineOption,
  toPerRiverOption,
  toInstitutionalOption,
  toHoldersOption,
  KLINE_RECENT,
  type KlineItem,
  type PerRiverItem,
  type InstitutionalItem,
  type HoldersItem,
} from "../chartOptions";
import { UP_COLORS, DOWN_COLORS } from "../theme";

// ── helpers ────────────────────────────────────────────────────────────────
function kline(overrides: Partial<KlineItem> = {}): KlineItem {
  return {
    date: "2026-07-01",
    open: 100,
    high: 110,
    low: 95,
    close: 105,
    volume: 1000,
    ...overrides,
  };
}

/** 取出 series 陣列（型別 narrow 供測試存取）。 */
function series(option: unknown): any[] {
  return (option as { series: any[] }).series;
}

describe("toKLineOption", () => {
  it("candlestick data 順序為 ECharts 格式 [open, close, low, high]", () => {
    const opt = toKLineOption([
      kline({ open: 100, high: 120, low: 90, close: 110 }),
    ]);
    const candle = series(opt).find((s) => s.type === "candlestick");
    // 注意：不是 OHLC，而是 [open, close, low, high]
    expect(candle.data[0]).toEqual([100, 110, 90, 120]);
  });

  it("陽線（close>open）itemStyle 用紅 UP_COLORS[1]、陰線用綠 DOWN_COLORS[1]", () => {
    const candle = series(toKLineOption([kline()])).find(
      (s) => s.type === "candlestick",
    );
    expect(candle.itemStyle.color).toBe(UP_COLORS[1]);
    expect(candle.itemStyle.color0).toBe(DOWN_COLORS[1]);
  });

  it("成交量 bar 逐筆依漲跌著色，與 K 棒同步（漲紅跌綠）", () => {
    const opt = toKLineOption([
      kline({ open: 100, close: 110 }), // 漲 → 紅
      kline({ open: 110, close: 100 }), // 跌 → 綠
    ]);
    const vol = series(opt).find((s) => s.type === "bar");
    expect(vol.data[0].itemStyle.color).toBe(UP_COLORS[1]);
    expect(vol.data[1].itemStyle.color).toBe(DOWN_COLORS[1]);
  });

  it("成交量 bar value 取原始 volume（含 null 容忍）", () => {
    const opt = toKLineOption([
      kline({ volume: 5000 }),
      kline({ volume: null }),
    ]);
    const vol = series(opt).find((s) => s.type === "bar");
    expect(vol.data[0].value).toBe(5000);
    expect(vol.data[1].value).toBeNull();
  });

  it("dataZoom 預設顯示最近 60 筆（>60 時起點裁切、end=100）", () => {
    const items = Array.from({ length: 100 }, (_, k) =>
      kline({ date: `d${k}` }),
    );
    const opt = toKLineOption(items);
    const dz = (opt as { dataZoom: any[] }).dataZoom;
    // 100 筆取尾 60 → start = (100-60)/100*100 = 40
    expect(dz[0].start).toBe(40);
    expect(dz[0].end).toBe(100);
  });

  it("dataZoom 資料不足 60 筆時從頭顯示（start=0）", () => {
    const items = Array.from({ length: 10 }, (_, k) => kline({ date: `d${k}` }));
    const dz = (toKLineOption(items) as { dataZoom: any[] }).dataZoom;
    expect(dz[0].start).toBe(0);
  });

  it("KLINE_RECENT 常數為 60", () => {
    expect(KLINE_RECENT).toBe(60);
  });
});

describe("toPerRiverOption", () => {
  function per(overrides: Partial<PerRiverItem> = {}): PerRiverItem {
    return {
      date: "2026-07-01",
      close: 100,
      band_p10: 80,
      band_p25: 90,
      band_p50: 100,
      band_p75: 110,
      band_p90: 120,
      ...overrides,
    };
  }

  it("含 close 折線 + 五條分位帶，共 6 系列", () => {
    const opt = toPerRiverOption([per()]);
    expect(series(opt)).toHaveLength(6);
    expect(series(opt).map((s) => s.name)).toEqual([
      "P10",
      "P25",
      "P50",
      "P75",
      "P90",
      "收盤",
    ]);
  });

  it("每條帶與 close 皆全為 line 且 connectNulls:false（null 日斷線）", () => {
    const opt = toPerRiverOption([per(), per({ band_p50: null, close: null })]);
    for (const s of series(opt)) {
      expect(s.type).toBe("line");
      expect(s.connectNulls).toBe(false);
    }
    const p50 = series(opt).find((s) => s.name === "P50");
    expect(p50.data).toEqual([100, null]); // null 保留 → 斷線
  });

  it("帶採 areaStyle 疊層填色（每條帶帶 areaStyle）", () => {
    const opt = toPerRiverOption([per()]);
    const bands = series(opt).filter((s) => s.name !== "收盤");
    for (const b of bands) {
      expect(b.areaStyle).toBeDefined();
      expect(b.areaStyle.opacity).toBeGreaterThan(0);
    }
    // 收盤線不填色（浮於帶之上）
    const close = series(opt).find((s) => s.name === "收盤");
    expect(close.areaStyle).toBeUndefined();
  });

  it("中位帶 P50 填色 opacity 高於最外側 P10/P90（疊出漸層）", () => {
    const opt = toPerRiverOption([per()]);
    const p50 = series(opt).find((s) => s.name === "P50");
    const p10 = series(opt).find((s) => s.name === "P10");
    expect(p50.areaStyle.opacity).toBeGreaterThan(p10.areaStyle.opacity);
  });
});

describe("toInstitutionalOption", () => {
  function inst(overrides: Partial<InstitutionalItem> = {}): InstitutionalItem {
    return {
      date: "2026-07-01",
      foreign_net: 100,
      trust_net: -50,
      dealer_net: 0,
      ...overrides,
    };
  }

  it("三系列 bar：外資／投信／自營商", () => {
    const opt = toInstitutionalOption([inst()]);
    expect(series(opt)).toHaveLength(3);
    expect(series(opt).map((s) => s.name)).toEqual(["外資", "投信", "自營商"]);
    for (const s of series(opt)) expect(s.type).toBe("bar");
  });

  it("正紅負綠、零與 null 中性著色", () => {
    const opt = toInstitutionalOption([
      inst({ foreign_net: 100, trust_net: -50, dealer_net: 0 }),
      inst({ foreign_net: null }),
    ]);
    const [foreign, trust, dealer] = series(opt);
    expect(foreign.data[0].itemStyle.color).toBe(UP_COLORS[1]); // 正 → 紅
    expect(trust.data[0].itemStyle.color).toBe(DOWN_COLORS[1]); // 負 → 綠
    expect(dealer.data[0].itemStyle.color).toBe("#3a4358"); // 0 → 中性
    expect(foreign.data[1].itemStyle.color).toBe("#3a4358"); // null → 中性
  });

  it("y 軸為 value 型（以零為基準軸）", () => {
    const opt = toInstitutionalOption([inst()]);
    const yAxis = (opt as { yAxis: { type: string } }).yAxis;
    expect(yAxis.type).toBe("value");
  });
});

describe("toHoldersOption", () => {
  function hold(overrides: Partial<HoldersItem> = {}): HoldersItem {
    return { week: "2026-W26", ratio_400up: 42.5, ...overrides };
  }

  it("單一週線 line + areaStyle", () => {
    const opt = toHoldersOption([hold(), hold({ week: "2026-W27" })]);
    expect(series(opt)).toHaveLength(1);
    const s = series(opt)[0];
    expect(s.type).toBe("line");
    expect(s.areaStyle).toBeDefined();
    expect(s.data).toEqual([42.5, 42.5]);
  });

  it("y 軸 axisLabel 以百分比格式（{value}%）", () => {
    const opt = toHoldersOption([hold()]);
    const yAxis = (opt as { yAxis: { axisLabel: { formatter: string } } }).yAxis;
    expect(yAxis.axisLabel.formatter).toBe("{value}%");
  });

  it("x 軸類別取 week 欄", () => {
    const opt = toHoldersOption([hold({ week: "2026-W26" })]);
    const xAxis = (opt as { xAxis: { data: string[] } }).xAxis;
    expect(xAxis.data).toEqual(["2026-W26"]);
  });
});
