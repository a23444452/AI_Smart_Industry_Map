import { describe, it, expect } from "vitest";
import {
  toTreemapData,
  UP_COLORS,
  DOWN_COLORS,
  FLAT_COLOR,
  type TreemapInput,
} from "../charts/toTreemapData";

function make(overrides: Partial<TreemapInput> = {}): TreemapInput {
  return {
    ticker: "2330",
    name: "台積電",
    change_pct: 1.25,
    ...overrides,
  };
}

describe("toTreemapData", () => {
  it("空輸入回傳空陣列", () => {
    expect(toTreemapData([])).toEqual([]);
  });

  it("排除 change_pct 為 null 的項目", () => {
    const out = toTreemapData([
      make({ ticker: "2330", change_pct: 1.25 }),
      make({ ticker: "2317", change_pct: null }),
    ]);
    expect(out).toHaveLength(1);
    expect(out[0].ticker).toBe("2330");
  });

  it("value = |change_pct|", () => {
    const out = toTreemapData([make({ change_pct: -2.5 })]);
    expect(out[0].value).toBe(2.5);
  });

  it("value 下限為 0.3（微小漲跌仍可見）", () => {
    const out = toTreemapData([
      make({ ticker: "a", change_pct: 0.01 }),
      make({ ticker: "b", change_pct: -0.05 }),
      make({ ticker: "c", change_pct: 0 }),
    ]);
    expect(out[0].value).toBe(0.3);
    expect(out[1].value).toBe(0.3);
    expect(out[2].value).toBe(0.3);
  });

  it("label 格式為 name 換行 +x.xx%（重用 formatPct）", () => {
    const out = toTreemapData([make({ name: "台積電", change_pct: 1.25 })]);
    expect(out[0].name).toBe("台積電\n+1.25%");
  });

  it("label 對負值帶負號兩位小數", () => {
    const out = toTreemapData([make({ name: "鴻海", change_pct: -0.95 })]);
    expect(out[0].name).toBe("鴻海\n-0.95%");
  });

  it("漲（>0）套用紅色系，依幅度分 4 級", () => {
    const out = toTreemapData([
      make({ ticker: "a", change_pct: 0.5 }), // <1% 最淺
      make({ ticker: "b", change_pct: 1.5 }), // ≥1% 中等
      make({ ticker: "c", change_pct: 3.2 }), // ≥3% 次深
      make({ ticker: "d", change_pct: 6.0 }), // ≥5% 最深
    ]);
    expect(out[0].itemStyle.color).toBe(UP_COLORS[0]);
    expect(out[1].itemStyle.color).toBe(UP_COLORS[1]);
    expect(out[2].itemStyle.color).toBe(UP_COLORS[2]);
    expect(out[3].itemStyle.color).toBe(UP_COLORS[3]);
  });

  it("跌（<0）套用綠色系，依幅度分 4 級", () => {
    const out = toTreemapData([
      make({ ticker: "a", change_pct: -0.5 }), // <1% 最淺
      make({ ticker: "b", change_pct: -1.5 }), // ≥1% 中等
      make({ ticker: "c", change_pct: -3.2 }), // ≥3% 次深
      make({ ticker: "d", change_pct: -6.0 }), // ≥5% 最深
    ]);
    expect(out[0].itemStyle.color).toBe(DOWN_COLORS[0]);
    expect(out[1].itemStyle.color).toBe(DOWN_COLORS[1]);
    expect(out[2].itemStyle.color).toBe(DOWN_COLORS[2]);
    expect(out[3].itemStyle.color).toBe(DOWN_COLORS[3]);
  });

  it("分級邊界為含下界（≥）", () => {
    const out = toTreemapData([
      make({ ticker: "a", change_pct: 1.0 }), // 恰 1% → 中等
      make({ ticker: "b", change_pct: 3.0 }), // 恰 3% → 次深
      make({ ticker: "c", change_pct: 5.0 }), // 恰 5% → 最深
    ]);
    expect(out[0].itemStyle.color).toBe(UP_COLORS[1]);
    expect(out[1].itemStyle.color).toBe(UP_COLORS[2]);
    expect(out[2].itemStyle.color).toBe(UP_COLORS[3]);
  });

  it("change_pct 為 0 套用灰色", () => {
    const out = toTreemapData([make({ change_pct: 0 })]);
    expect(out[0].itemStyle.color).toBe(FLAT_COLOR);
  });
});
