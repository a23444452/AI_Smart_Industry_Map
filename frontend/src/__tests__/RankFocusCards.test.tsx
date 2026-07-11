import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { RankFocusCards } from "../components/topics/RankFocusCards";
import type { TopicSummary } from "../api/topics";

// 排行 fixture
const topic: TopicSummary = {
  slug: "silicon-photonics",
  title: "矽光子",
  description: "描述",
  market_tab: "tw",
  company_count: 17,
  verified_at: "2026-07-11",
  change_pct_avg: 2.5,
};

describe("RankFocusCards", () => {
  it("點擊漲/跌 toggle 觸發 onDirectionChange，且 active 鈕帶 aria-pressed", () => {
    const onChange = vi.fn();
    render(
      <RankFocusCards rank={[topic]} direction="up" onDirectionChange={onChange} />,
    );
    const downBtn = screen.getByRole("button", { name: "跌" });
    fireEvent.click(downBtn);
    expect(onChange).toHaveBeenCalledWith("down");
    expect(screen.getByRole("button", { name: "漲" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(downBtn).toHaveAttribute("aria-pressed", "false");
  });

  it("rank 為空時顯示「今日尚無資料」佔位", () => {
    render(
      <RankFocusCards rank={[]} direction="up" onDirectionChange={() => {}} />,
    );
    expect(screen.getByText("今日尚無資料")).toBeInTheDocument();
  });

  it("isLoading 顯示 skeleton，且不顯示「今日尚無資料」", () => {
    render(
      <RankFocusCards
        rank={[]}
        direction="up"
        onDirectionChange={() => {}}
        isLoading
      />,
    );
    expect(screen.getAllByTestId("rank-skeleton")).toHaveLength(3);
    expect(screen.queryByText("今日尚無資料")).toBeNull();
  });

  it("isError 顯示錯誤語意，且不顯示「今日尚無資料」", () => {
    render(
      <RankFocusCards
        rank={[]}
        direction="up"
        onDirectionChange={() => {}}
        isError
      />,
    );
    expect(screen.getByText(/焦點載入失敗/)).toBeInTheDocument();
    expect(screen.queryByText("今日尚無資料")).toBeNull();
  });
});
