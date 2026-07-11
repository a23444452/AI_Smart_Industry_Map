import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { TopicCard } from "../components/topics/TopicCard";
import type { TopicSummary } from "../api/topics";

// TopicCard 標題含 <Link>，需 Router context 才能渲染
function renderCard(topic: TopicSummary) {
  return render(
    <MemoryRouter>
      <TopicCard topic={topic} />
    </MemoryRouter>,
  );
}

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
    renderCard(makeTopic());
    expect(screen.getByText("矽光子")).toBeInTheDocument();
    expect(screen.getByText("17 家公司")).toBeInTheDocument();
    expect(screen.getByText("核實於 2026-07-11")).toBeInTheDocument();
    expect(
      screen.getByText(/矽光子技術結合光學與半導體/),
    ).toBeInTheDocument();
  });

  it("change_pct_avg 為正時顯示 +x.xx% 並套用 text-up（紅漲）", () => {
    renderCard(makeTopic({ change_pct_avg: 1.25 }));
    const pct = screen.getByText("+1.25%");
    expect(pct).toBeInTheDocument();
    expect(pct).toHaveClass("text-up");
  });

  it("change_pct_avg 為負時顯示 -x.xx% 並套用 text-down（綠跌）", () => {
    renderCard(makeTopic({ change_pct_avg: -0.95 }));
    const pct = screen.getByText("-0.95%");
    expect(pct).toBeInTheDocument();
    expect(pct).toHaveClass("text-down");
  });

  it("change_pct_avg 為 null 時顯示 --", () => {
    renderCard(makeTopic({ change_pct_avg: null }));
    expect(screen.getByText("--")).toBeInTheDocument();
  });

  it("公司數徽章依 props 動態呈現", () => {
    renderCard(makeTopic({ company_count: 3 }));
    expect(screen.getByText("3 家公司")).toBeInTheDocument();
  });

  it("description/verified_at 為 null 時不渲染對應區塊", () => {
    renderCard(makeTopic({ description: null, verified_at: null }));
    expect(screen.queryByText(/矽光子技術結合光學與半導體/)).toBeNull();
    expect(screen.queryByText(/核實於/)).toBeNull();
  });

  it("探索產業地圖為啟用連結，指向 /topic/:slug/map", () => {
    renderCard(makeTopic({ slug: "silicon-photonics" }));
    const link = screen.getByRole("link", { name: "探索產業地圖" });
    expect(link).toHaveAttribute("href", "/topic/silicon-photonics/map");
  });
});
