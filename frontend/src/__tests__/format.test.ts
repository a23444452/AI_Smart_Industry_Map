import { describe, it, expect } from "vitest";
import { formatDateTaipei, formatYi } from "../lib/format";

describe("formatDateTaipei", () => {
  it("UTC ISO 轉台北時區日期（2026-07-11T00:00:00Z → 2026/7/11）", () => {
    expect(formatDateTaipei("2026-07-11T00:00:00Z")).toBe("2026/7/11");
  });

  it("跨日邊界：UTC 深夜為台北隔日（2026-07-11T22:00:00Z → 2026/7/12）", () => {
    expect(formatDateTaipei("2026-07-11T22:00:00Z")).toBe("2026/7/12");
  });

  it("null 回傳 null", () => {
    expect(formatDateTaipei(null)).toBeNull();
  });

  it("無法解析的字串回傳 null", () => {
    expect(formatDateTaipei("not-a-date")).toBeNull();
  });
});

describe("formatYi", () => {
  it("null → --", () => {
    expect(formatYi(null)).toBe("--");
  });

  it("≥1億：9,494,954,521 元 → 94.9億", () => {
    expect(formatYi(9494954521)).toBe("94.9億");
  });

  it("整數億去除 .0：500,000,000 → 5億", () => {
    expect(formatYi(500_000_000)).toBe("5億");
  });

  it("負數帶前綴 ASCII 減號：-94.9億", () => {
    expect(formatYi(-9494954521)).toBe("-94.9億");
  });

  it("<1億 以萬顯示、四捨五入加千分位：12,345,678 → 1,235萬", () => {
    expect(formatYi(12345678)).toBe("1,235萬");
  });

  it("0 → 0萬", () => {
    expect(formatYi(0)).toBe("0萬");
  });

  it("恰為 1 億 → 1億", () => {
    expect(formatYi(100_000_000)).toBe("1億");
  });

  it("億下界內側：99,990,000 → 9,999萬", () => {
    expect(formatYi(99_990_000)).toBe("9,999萬");
  });

  it("窄帶進位：99,995,000 四捨五入滿 10,000 萬 → 1億", () => {
    expect(formatYi(99_995_000)).toBe("1億");
  });
});
