import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { Treemap } from "../Treemap";
import type { TreemapInput } from "../toTreemapData";
import { useEChart } from "../chartsCore";

// mock useEChart：jsdom 無 canvas，且要驗證空資料時不 init chart（不呼叫 useEChart）。
vi.mock("../chartsCore", () => ({
  useEChart: vi.fn(() => ({ current: null })),
}));

const mockUseEChart = vi.mocked(useEChart);

describe("Treemap 空資料佔位（P4）", () => {
  beforeEach(() => {
    mockUseEChart.mockClear();
  });

  it("items=[] → 顯示「暫無資料」且不 init chart", () => {
    render(<Treemap items={[]} />);
    expect(screen.getByText("暫無資料")).toBeInTheDocument();
    expect(mockUseEChart).not.toHaveBeenCalled();
  });

  it("有資料 → 不顯示佔位、init chart（呼叫 useEChart）", () => {
    const items: TreemapInput[] = [
      { ticker: "2330", name: "台積電", change_pct: 1.5 },
    ];
    render(<Treemap items={items} />);
    expect(screen.queryByText("暫無資料")).toBeNull();
    expect(mockUseEChart).toHaveBeenCalled();
  });
});
