import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MarginTable } from "../MarginTable";
import type { MarginRow } from "../../../api/daily";

function marginRow(overrides: Partial<MarginRow> = {}): MarginRow {
  return {
    item: "融資金額(仟元)",
    buy: 1234567,
    sell: 987654,
    prev_balance: 5000000,
    today_balance: 5100000,
    ...overrides,
  };
}

describe("MarginTable", () => {
  it("item 以原名顯示、數值千分位不換算", () => {
    render(
      <MarginTable data={{ date: "2026-07-11", rows: [marginRow()] }} />,
    );
    expect(screen.getByText("融資金額(仟元)")).toBeInTheDocument();
    expect(screen.getByText("1,234,567")).toBeInTheDocument();
    expect(screen.getByText("5,100,000")).toBeInTheDocument();
  });

  it("null 值顯示 —", () => {
    render(
      <MarginTable
        data={{ date: "2026-07-11", rows: [marginRow({ buy: null })] }}
      />,
    );
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("空表 → 顯示佔位", () => {
    render(<MarginTable data={{ date: null, rows: [] }} />);
    expect(screen.getByText("暫無資券資料")).toBeInTheDocument();
  });
});
