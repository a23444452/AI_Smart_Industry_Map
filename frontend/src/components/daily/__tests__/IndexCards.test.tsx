import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { IndexCards } from "../IndexCards";
import type { IndexRow } from "../../../api/daily";

function row(overrides: Partial<IndexRow> = {}): IndexRow {
  return {
    symbol: "^TWII",
    name: "加權指數",
    price: 23456.78,
    change: 120.5,
    change_pct: 1.25,
    fetched_at: "2026-07-11T05:00:00Z",
    ...overrides,
  };
}

describe("IndexCards", () => {
  it("渲染名稱與千分位現值", () => {
    render(<IndexCards indices={[row({ price: 23456.78 })]} />);
    expect(screen.getByText("加權指數")).toBeInTheDocument();
    expect(screen.getByText("23,456.78")).toBeInTheDocument();
  });

  it("漲：change_pct 正值以 formatPct 顯示且套紅漲 class", () => {
    render(<IndexCards indices={[row({ change_pct: 1.25 })]} />);
    const el = screen.getByText("+1.25%");
    expect(el).toBeInTheDocument();
    expect(el.className).toContain("text-up");
  });

  it("跌：change_pct 負值套綠跌 class", () => {
    render(<IndexCards indices={[row({ change_pct: -0.95 })]} />);
    const el = screen.getByText("-0.95%");
    expect(el.className).toContain("text-down");
  });

  it("change_pct 為 null → 顯示 -- 且 dim", () => {
    render(<IndexCards indices={[row({ change_pct: null })]} />);
    const el = screen.getByText("--");
    expect(el.className).toContain("text-text-dim");
  });

  it("空陣列 → 顯示佔位", () => {
    render(<IndexCards indices={[]} />);
    expect(screen.getByText("暫無指數資料")).toBeInTheDocument();
  });
});
