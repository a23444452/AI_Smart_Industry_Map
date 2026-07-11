import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { TopicCard } from "../components/topics/TopicCard";
import type { TopicSummary } from "../api/topics";

// 基底 fixture：測試中以 override 覆寫個別欄位
function makeTopic(overrides: Partial<TopicSummary> = {}): TopicSummary {
  return {
    slug: "silicon-photonics",
    title: "矽光子",
    description: "矽光子技術結合光學與半導體，應用於高速資料中心互連。",
    market_tab: "tw",
    company_count: 17,
    verified_at: "2026-07-11",
    change_pct_avg: 1.25,
    ...overrides,
  };
}

describe("TopicCard", () => {
  it("顯示 title、公司數徽章、核實日期與 description", () => {
    render(<TopicCard topic={makeTopic()} />);
    expect(screen.getByText("矽光子")).toBeInTheDocument();
    expect(screen.getByText("17 家公司")).toBeInTheDocument();
    expect(screen.getByText("核實於 2026-07-11")).toBeInTheDocument();
    expect(
      screen.getByText(/矽光子技術結合光學與半導體/),
    ).toBeInTheDocument();
  });

  it("change_pct_avg 為正時顯示 +x.xx% 並套用 text-up（紅漲）", () => {
    render(<TopicCard topic={makeTopic({ change_pct_avg: 1.25 })} />);
    const pct = screen.getByText("+1.25%");
    expect(pct).toBeInTheDocument();
    expect(pct).toHaveClass("text-up");
  });

  it("change_pct_avg 為負時顯示 -x.xx% 並套用 text-down（綠跌）", () => {
    render(<TopicCard topic={makeTopic({ change_pct_avg: -0.95 })} />);
    const pct = screen.getByText("-0.95%");
    expect(pct).toBeInTheDocument();
    expect(pct).toHaveClass("text-down");
  });

  it("change_pct_avg 為 null 時顯示 --", () => {
    render(<TopicCard topic={makeTopic({ change_pct_avg: null })} />);
    expect(screen.getByText("--")).toBeInTheDocument();
  });

  it("公司數徽章依 props 動態呈現", () => {
    render(<TopicCard topic={makeTopic({ company_count: 3 })} />);
    expect(screen.getByText("3 家公司")).toBeInTheDocument();
  });
});
