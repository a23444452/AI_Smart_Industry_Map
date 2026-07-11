import { describe, it, expect } from "vitest";
import { formatDateTaipei } from "../lib/format";

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
