import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { CompanyCard } from "../CompanyCard";
import type { MapCompany } from "../../../api/topicMap";

function makeCompany(overrides: Partial<MapCompany> = {}): MapCompany {
  return {
    ticker: "2330",
    name: "台積電",
    role: "龍頭",
    relevance: "高",
    close: 2415,
    change_pct: 1.25,
    badges: [],
    ...overrides,
  };
}

describe("CompanyCard", () => {
  it("顯示公司名稱與 ticker", () => {
    render(<CompanyCard company={makeCompany()} />);
    expect(screen.getByText("台積電")).toBeInTheDocument();
    expect(screen.getByText("2330")).toBeInTheDocument();
  });

  it("close 以千分位顯示、無小數尾零（2,415）；null → --", () => {
    const { rerender } = render(
      <CompanyCard company={makeCompany({ close: 2415 })} />,
    );
    expect(screen.getByText("2,415")).toBeInTheDocument();

    rerender(<CompanyCard company={makeCompany({ close: null })} />);
    expect(screen.getByText("--")).toBeInTheDocument();
  });

  it("change_pct 帶符號帶色（+1.25%）；null → -- dim", () => {
    const { rerender } = render(
      <CompanyCard company={makeCompany({ change_pct: 1.25 })} />,
    );
    const up = screen.getByText("+1.25%");
    expect(up).toBeInTheDocument();
    expect(up.className).toContain("text-up");

    rerender(<CompanyCard company={makeCompany({ change_pct: -0.95 })} />);
    const down = screen.getByText("-0.95%");
    expect(down.className).toContain("text-down");

    rerender(<CompanyCard company={makeCompany({ change_pct: null })} />);
    const dim = screen.getByText("--");
    expect(dim.className).toContain("text-text-dim");
  });

  it("角色標籤：已知 role 映射顯示、未知原樣不炸；relevance 關聯度", () => {
    const { rerender } = render(
      <CompanyCard company={makeCompany({ role: "龍頭", relevance: "高" })} />,
    );
    expect(screen.getByText(/產業龍頭/)).toBeInTheDocument();
    expect(screen.getByText(/高 關聯度/)).toBeInTheDocument();

    rerender(<CompanyCard company={makeCompany({ role: "利基" })} />);
    expect(screen.getByText(/利基專精/)).toBeInTheDocument();

    rerender(<CompanyCard company={makeCompany({ role: "新興" })} />);
    expect(screen.getByText(/新興初期/)).toBeInTheDocument();

    rerender(<CompanyCard company={makeCompany({ role: "挑戰" })} />);
    expect(screen.getByText(/成長挑戰/)).toBeInTheDocument();

    // 未知 role 原樣顯示不炸
    rerender(<CompanyCard company={makeCompany({ role: "神秘角色" })} />);
    expect(screen.getByText(/神秘角色/)).toBeInTheDocument();
  });

  it("role null → 中性 chip「未分類」；relevance null → 「— 關聯度」", () => {
    render(
      <CompanyCard company={makeCompany({ role: null, relevance: null })} />,
    );
    expect(screen.getByText("未分類")).toBeInTheDocument();
    expect(screen.getByText(/— 關聯度/)).toBeInTheDocument();
  });

  it("badges：非空 → 每個 chip；空陣列 → 不渲染徽章", () => {
    const { rerender } = render(
      <CompanyCard
        company={makeCompany({ badges: ["有股票期貨", "投信買超"] })}
      />,
    );
    expect(screen.getByText("有股票期貨")).toBeInTheDocument();
    expect(screen.getByText("投信買超")).toBeInTheDocument();

    rerender(<CompanyCard company={makeCompany({ badges: [] })} />);
    expect(screen.queryByText("有股票期貨")).not.toBeInTheDocument();
  });
});
