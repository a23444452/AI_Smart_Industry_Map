import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { CompanyTable } from "../CompanyTable";
import type { CompanyListItem } from "../../../api/companies";

function item(overrides: Partial<CompanyListItem> = {}): CompanyListItem {
  return {
    ticker: "2330",
    name: "台積電",
    market: "twse",
    topics: ["silicon-photonics"],
    close: 1234.5,
    change_pct: 2.5,
    per: 18.3,
    revenue_yoy: 12.4,
    ...overrides,
  };
}

function renderTable(items: CompanyListItem[]) {
  return render(
    <MemoryRouter>
      <CompanyTable items={items} />
    </MemoryRouter>,
  );
}

describe("CompanyTable", () => {
  it("渲染列：名稱、收盤千分位、PER", () => {
    renderTable([item()]);
    expect(screen.getByText("台積電")).toBeInTheDocument();
    expect(screen.getByText("1,234.5")).toBeInTheDocument();
    expect(screen.getByText("18.30")).toBeInTheDocument();
  });

  it("漲跌幅帶色帶符號（正紅）", () => {
    renderTable([item({ change_pct: 2.5 })]);
    const pct = screen.getByText("+2.50%");
    expect(pct.className).toContain("text-up");
  });

  it("代號為連往個股頁的 Link（/c/{ticker}）", () => {
    renderTable([item({ ticker: "2454" })]);
    expect(screen.getByRole("link", { name: "2454" })).toHaveAttribute(
      "href",
      "/c/2454",
    );
  });

  it("revenue_yoy 為 null → 顯示 --", () => {
    renderTable([item({ ticker: "6488", revenue_yoy: null })]);
    // per 仍有值，唯一的 "--" 來自 revenue_yoy 欄
    expect(screen.getByText("--")).toBeInTheDocument();
  });

  it("per 與 close 皆 null → 各顯示 --", () => {
    renderTable([item({ per: null, close: null, revenue_yoy: 5 })]);
    expect(screen.getAllByText("--")).toHaveLength(2);
  });

  it("空清單 → 顯示佔位、不渲染表格", () => {
    renderTable([]);
    expect(screen.getByText("查無符合條件的公司")).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
  });
});
