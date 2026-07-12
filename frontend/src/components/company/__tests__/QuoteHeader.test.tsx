import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QuoteHeader } from "../QuoteHeader";
import type { CompanyDetail } from "../../../api/companies";

function detail(overrides: Partial<CompanyDetail> = {}): CompanyDetail {
  return {
    ticker: "2330",
    name: "台積電",
    market: "twse",
    close: 1085,
    change: 15,
    change_pct: 1.4,
    volume: 25_600_000,
    topics: [{ slug: "silicon-photonics", title: "矽光子" }],
    badges: ["可當沖", "有期貨"],
    per: 22.5,
    pbr: 6.1,
    dividend_yield: 1.85,
    latest_revenue: { month: "2026-06", revenue: 200_000, yoy: 30.2 },
    major_holder: { week: "2026-W26", ratio_400up: 78.3 },
    quotes_updated_at: "2026-07-11T00:00:00Z",
    ...overrides,
  };
}

function renderHeader(company: CompanyDetail) {
  return render(
    <MemoryRouter>
      <QuoteHeader company={company} />
    </MemoryRouter>,
  );
}

describe("QuoteHeader", () => {
  it("渲染名稱、代號與收盤大字（千分位）", () => {
    renderHeader(detail());
    expect(screen.getByRole("heading", { name: "台積電" })).toBeInTheDocument();
    expect(screen.getByText("2330")).toBeInTheDocument();
    expect(screen.getByText("1,085")).toBeInTheDocument();
  });

  it("漲跌值與幅帶符號帶色（正紅）", () => {
    renderHeader(detail({ change: 15, change_pct: 1.4 }));
    const el = screen.getByText("+15.00 (+1.40%)");
    expect(el.className).toContain("text-up");
  });

  it("下跌帶色（負綠）", () => {
    renderHeader(detail({ change: -8.5, change_pct: -0.75 }));
    const el = screen.getByText("-8.50 (-0.75%)");
    expect(el.className).toContain("text-down");
  });

  it("成交量由股換算為張（÷1000 取整、千分位）", () => {
    renderHeader(detail({ volume: 25_600_000 }));
    expect(screen.getByText("成交量 25,600 張")).toBeInTheDocument();
  });

  it("估值列渲染 PER／PBR／殖利率／營收年增／大戶持股比", () => {
    renderHeader(detail());
    expect(screen.getByText("22.50")).toBeInTheDocument(); // PER
    expect(screen.getByText("6.10")).toBeInTheDocument(); // PBR
    expect(screen.getByText("1.85%")).toBeInTheDocument(); // 殖利率
    expect(screen.getByText("+30.20%")).toBeInTheDocument(); // 營收年增
    expect(screen.getByText("78.30%")).toBeInTheDocument(); // 大戶持股比
  });

  it("估值缺值（含 revenue／holder 為 null）→ 顯示 --", () => {
    renderHeader(
      detail({
        per: null,
        pbr: null,
        dividend_yield: null,
        latest_revenue: null,
        major_holder: null,
        volume: null,
      }),
    );
    // 五個估值欄 + 成交量張，皆為 --
    expect(screen.getAllByText("--").length).toBeGreaterThanOrEqual(5);
  });

  it("徽章 chips 渲染", () => {
    renderHeader(detail({ badges: ["可當沖", "有期貨"] }));
    expect(screen.getByText("可當沖")).toBeInTheDocument();
    expect(screen.getByText("有期貨")).toBeInTheDocument();
  });

  it("題材 chips 為連往題材詳情頁的 Link（/topic/{slug}）", () => {
    renderHeader(detail());
    expect(screen.getByRole("link", { name: "矽光子" })).toHaveAttribute(
      "href",
      "/topic/silicon-photonics",
    );
  });
});
