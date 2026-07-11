import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MetricsCard } from "../MetricsCard";

describe("MetricsCard", () => {
  it("已知 key 以中文 label 映射並顯示 value", () => {
    render(<MetricsCard metrics={{ cagr: "45%+", market_size: "10.2 (USD B)" }} />);
    expect(screen.getByText("CAGR")).toBeInTheDocument();
    expect(screen.getByText("45%+")).toBeInTheDocument();
    expect(screen.getByText("市場規模")).toBeInTheDocument();
    expect(screen.getByText("10.2 (USD B)")).toBeInTheDocument();
  });

  it("完整映射表：tech_core / main_spec / commercial_node / barrier", () => {
    render(
      <MetricsCard
        metrics={{
          tech_core: "光學",
          main_spec: "800G",
          commercial_node: "2026",
          barrier: "製程",
        }}
      />,
    );
    expect(screen.getByText("技術核心")).toBeInTheDocument();
    expect(screen.getByText("主力規格")).toBeInTheDocument();
    expect(screen.getByText("商轉節點")).toBeInTheDocument();
    expect(screen.getByText("產業門檻")).toBeInTheDocument();
  });

  it("未知 key 原樣顯示", () => {
    render(<MetricsCard metrics={{ foo_bar: "值" }} />);
    expect(screen.getByText("foo_bar")).toBeInTheDocument();
    expect(screen.getByText("值")).toBeInTheDocument();
  });

  it("空 metrics 不渲染任何項目", () => {
    const { container } = render(<MetricsCard metrics={{}} />);
    expect(container.querySelectorAll("dt")).toHaveLength(0);
  });
});
