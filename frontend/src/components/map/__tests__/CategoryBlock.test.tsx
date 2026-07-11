import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { CategoryBlock } from "../CategoryBlock";
import type { MapCategory, MapCompany } from "../../../api/topicMap";

function makeCompany(i: number): MapCompany {
  return {
    ticker: `${1000 + i}`,
    name: `公司${i}`,
    role: "龍頭",
    relevance: "高",
    close: 100 + i,
    change_pct: 1,
    badges: [],
  };
}

function makeCategory(overrides: Partial<MapCategory> = {}): MapCategory {
  return {
    name: "晶圓代工",
    desc: "先進製程龍頭群",
    placeholder: false,
    companies: [makeCompany(1), makeCompany(2)],
    ...overrides,
  };
}

describe("CategoryBlock", () => {
  it("顯示 name、desc 與 N 家公司", () => {
    render(<CategoryBlock category={makeCategory()} />);
    expect(screen.getByText("晶圓代工")).toBeInTheDocument();
    expect(screen.getByText("先進製程龍頭群")).toBeInTheDocument();
    expect(screen.getByText(/2 家公司/)).toBeInTheDocument();
  });

  it("placeholder=true → 待補充空狀態，不渲染公司", () => {
    render(
      <CategoryBlock
        category={makeCategory({ placeholder: true, companies: [] })}
      />,
    );
    expect(screen.getByText(/待補充/)).toBeInTheDocument();
    expect(screen.queryByText("公司1")).not.toBeInTheDocument();
  });

  it("companies > 5 → 預設顯示前 5 ＋顯示更多按鈕，點擊展開後可收合", () => {
    const companies = Array.from({ length: 8 }, (_, i) => makeCompany(i + 1));
    render(<CategoryBlock category={makeCategory({ companies })} />);

    // 預設只前 5 檔
    expect(screen.getByText("公司5")).toBeInTheDocument();
    expect(screen.queryByText("公司6")).not.toBeInTheDocument();

    // 剩餘 3 檔 → 顯示更多 (3)
    const moreBtn = screen.getByRole("button", { name: /顯示更多 \(3\)/ });
    fireEvent.click(moreBtn);
    expect(screen.getByText("公司6")).toBeInTheDocument();
    expect(screen.getByText("公司8")).toBeInTheDocument();

    // 展開後按鈕變收合
    const collapseBtn = screen.getByRole("button", { name: /收合/ });
    fireEvent.click(collapseBtn);
    expect(screen.queryByText("公司6")).not.toBeInTheDocument();
  });

  it("companies <= 5 → 無顯示更多按鈕", () => {
    const companies = Array.from({ length: 5 }, (_, i) => makeCompany(i + 1));
    render(<CategoryBlock category={makeCategory({ companies })} />);
    expect(
      screen.queryByRole("button", { name: /顯示更多/ }),
    ).not.toBeInTheDocument();
  });
});
