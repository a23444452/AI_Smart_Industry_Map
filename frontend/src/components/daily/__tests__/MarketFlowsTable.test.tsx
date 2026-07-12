import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MarketFlowsTable } from "../MarketFlowsTable";
import type { FlowRow, MarketFlows } from "../../../api/daily";

function flow(overrides: Partial<FlowRow> = {}): FlowRow {
  return { unit: "投信", buy: 100, sell: 50, net: 50, ...overrides };
}

function data(rows: FlowRow[]): MarketFlows {
  return { date: "2026-07-11", rows };
}

describe("MarketFlowsTable", () => {
  it("身份別顯示映射：來源原名 → 精簡名", () => {
    render(
      <MarketFlowsTable
        data={data([
          flow({ unit: "自營商(自行買賣)" }),
          flow({ unit: "外資及陸資(不含外資自營商)" }),
          flow({ unit: "自營商(避險)" }),
        ])}
      />,
    );
    expect(screen.getByText("自營商")).toBeInTheDocument();
    expect(screen.getByText("外資")).toBeInTheDocument();
    expect(screen.getByText("自營商避險")).toBeInTheDocument();
  });

  it("未知 unit 原樣顯示", () => {
    render(<MarketFlowsTable data={data([flow({ unit: "合計" })])} />);
    expect(screen.getByText("合計")).toBeInTheDocument();
  });

  it("金額 formatYi：9,494,954,521 元 → 94.9億", () => {
    render(
      <MarketFlowsTable data={data([flow({ buy: 9494954521, net: null })])} />,
    );
    expect(screen.getByText("94.9億")).toBeInTheDocument();
  });

  it("net 正值套紅漲 class、負值套綠跌 class", () => {
    const { rerender } = render(
      <MarketFlowsTable data={data([flow({ unit: "投信", net: 5_0000_0000 })])} />,
    );
    expect(screen.getByText("5億").className).toContain("text-up");

    rerender(
      <MarketFlowsTable data={data([flow({ unit: "投信", net: -5_0000_0000 })])} />,
    );
    expect(screen.getByText("−5億").className).toContain("text-down");
  });

  it("空表 → 顯示佔位", () => {
    render(<MarketFlowsTable data={data([])} />);
    expect(screen.getByText("暫無法人資料")).toBeInTheDocument();
  });
});
