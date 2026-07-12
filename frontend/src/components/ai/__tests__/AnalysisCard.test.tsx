import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { AnalysisCard } from "../AnalysisCard";
import type { AnalysisCardData } from "../AnalysisCard";

function card(overrides: Partial<AnalysisCardData> = {}): AnalysisCardData {
  return {
    ticker: "2330",
    name: "台積電",
    mode: "近期觀察",
    status: "done",
    scores: { 題材面: 80, 基本面: 70, 技術面: 60, 籌碼面: 90, 新聞面: 50 },
    summary: "綜合五面向平均 70 分。",
    total: 70,
    model: "anthropic:claude-sonnet-5",
    error: null,
    created_at: "2026-07-11T00:00:00Z",
    ...overrides,
  };
}

describe("AnalysisCard", () => {
  it("渲染 ticker、name 與 mode chip", () => {
    render(<AnalysisCard data={card()} />);
    expect(screen.getByText("2330")).toBeInTheDocument();
    expect(screen.getByText("台積電")).toBeInTheDocument();
    expect(screen.getByText("近期觀察")).toBeInTheDocument();
  });

  it("渲染五面向 ScoreBars 與 total 大字", () => {
    render(<AnalysisCard data={card({ total: 78.5 })} />);
    expect(screen.getByText("題材面")).toBeInTheDocument();
    expect(screen.getByText("籌碼面")).toBeInTheDocument();
    expect(screen.getByText("78.5")).toBeInTheDocument();
  });

  it("created_at 以台北時區日期顯示", () => {
    render(<AnalysisCard data={card({ created_at: "2026-07-11T22:00:00Z" })} />);
    // 台北為隔日
    expect(screen.getByText("2026/7/12")).toBeInTheDocument();
  });

  it("model 為 mock → 顯示「模擬分析」badge", () => {
    render(<AnalysisCard data={card({ model: "mock" })} />);
    expect(screen.getByText("模擬分析")).toBeInTheDocument();
  });

  it("model 非 mock → 不顯示「模擬分析」badge", () => {
    render(<AnalysisCard data={card({ model: "anthropic:claude-sonnet-5" })} />);
    expect(screen.queryByText("模擬分析")).not.toBeInTheDocument();
  });

  it("status 為 failed → 顯示 error 訊息、不渲染 ScoreBars", () => {
    render(
      <AnalysisCard
        data={card({
          status: "failed",
          error: "AI 服務暫時無法使用，請稍後再試。",
          scores: null,
          total: null,
        })}
      />,
    );
    expect(
      screen.getByText("AI 服務暫時無法使用，請稍後再試。"),
    ).toBeInTheDocument();
    // 失敗態不渲染分數條
    expect(screen.queryByTestId("bar-題材面")).not.toBeInTheDocument();
  });

  it("有 reasons → 顯示「查看各面向理由」展開區，逐面向每句一行", () => {
    render(
      <AnalysisCard
        data={card({
          reasons: {
            題材面: ["題材動能強勁。", "AI 供應鏈核心。"],
            基本面: ["營收年增穩健。"],
          },
        })}
      />,
    );
    expect(screen.getByText("查看各面向理由")).toBeInTheDocument();
    // <details> 內容於 DOM 中存在（jsdom 不受展開狀態影響）
    expect(screen.getByText("題材動能強勁。")).toBeInTheDocument();
    expect(screen.getByText("AI 供應鏈核心。")).toBeInTheDocument();
    expect(screen.getByText("營收年增穩健。")).toBeInTheDocument();
  });

  it("reasons 為 null 或未提供 → 不渲染展開區", () => {
    render(<AnalysisCard data={card({ reasons: null })} />);
    expect(screen.queryByText("查看各面向理由")).not.toBeInTheDocument();
  });
});
