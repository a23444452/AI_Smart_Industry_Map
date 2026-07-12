import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ScoreBars } from "../ScoreBars";
import { ASPECTS } from "../../../api/ai";

describe("ScoreBars", () => {
  it("渲染五面向橫條（每面向一列，含標籤）", () => {
    render(<ScoreBars scores={{ 題材面: 80, 基本面: 70, 技術面: 60, 籌碼面: 90, 新聞面: 50 }} />);
    for (const aspect of ASPECTS) {
      expect(screen.getByText(aspect)).toBeInTheDocument();
    }
    // 五條 bar
    expect(screen.getAllByTestId(/^bar-/)).toHaveLength(5);
  });

  it("分數字與寬度%對應（72 → width 72%、顯示 72）", () => {
    render(<ScoreBars scores={{ 題材面: 72, 基本面: 0, 技術面: 100, 籌碼面: 45, 新聞面: 88 }} />);
    expect(screen.getByTestId("bar-題材面")).toHaveStyle({ width: "72%" });
    expect(screen.getByTestId("score-題材面")).toHaveTextContent("72");
    expect(screen.getByTestId("bar-技術面")).toHaveStyle({ width: "100%" });
  });

  it("缺鍵的面向 → 0 寬 + 「--」", () => {
    // 只給兩鍵，其餘三面向缺
    render(<ScoreBars scores={{ 題材面: 80, 基本面: 70 }} />);
    expect(screen.getByTestId("bar-技術面")).toHaveStyle({ width: "0%" });
    expect(screen.getByTestId("score-技術面")).toHaveTextContent("--");
    expect(screen.getByTestId("score-籌碼面")).toHaveTextContent("--");
  });

  it("scores 為 null → 全部佔位（五條 0 寬、分數 --）", () => {
    render(<ScoreBars scores={null} />);
    for (const aspect of ASPECTS) {
      expect(screen.getByTestId(`bar-${aspect}`)).toHaveStyle({ width: "0%" });
      expect(screen.getByTestId(`score-${aspect}`)).toHaveTextContent("--");
    }
  });
});
