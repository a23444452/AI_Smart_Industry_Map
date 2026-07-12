import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { MoversRanking } from "../MoversRanking";
import type { MoverItem, Movers } from "../../../api/daily";

/** MoversRanking 內含 <Link>，需 Router 情境。 */
function renderRanking(movers: Movers) {
  return render(
    <MemoryRouter>
      <MoversRanking movers={movers} />
    </MemoryRouter>,
  );
}

function item(overrides: Partial<MoverItem> = {}): MoverItem {
  return {
    ticker: "2330",
    name: "台積電",
    close: 1000,
    change_pct: 5.5,
    ...overrides,
  };
}

function makeMovers(overrides: Partial<Movers> = {}): Movers {
  return {
    day: [item({ ticker: "2330", name: "台積電", change_pct: 5.5 })],
    week: [item({ ticker: "2454", name: "聯發科", change_pct: 8.2 })],
    month: [],
    ...overrides,
  };
}

describe("MoversRanking", () => {
  it("標題為「強勢股排行」", () => {
    renderRanking(makeMovers());
    expect(
      screen.getByRole("heading", { name: "強勢股排行" }),
    ).toBeInTheDocument();
  });

  it("預設日 tab 為 pressed，渲染排名列（代號／名稱／收盤／漲跌幅帶色）", () => {
    renderRanking(makeMovers());
    expect(screen.getByRole("button", { name: "日" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByText("2330")).toBeInTheDocument();
    expect(screen.getByText("台積電")).toBeInTheDocument();
    expect(screen.getByText("1,000")).toBeInTheDocument();
    const pct = screen.getByText("+5.50%");
    expect(pct.className).toContain("text-up");
  });

  it("代號為連往個股頁的 Link（/c/{ticker}）", () => {
    renderRanking(makeMovers());
    expect(screen.getByRole("link", { name: "2330" })).toHaveAttribute(
      "href",
      "/c/2330",
    );
  });

  it("含「排行範圍：已收錄個股」註記", () => {
    renderRanking(makeMovers());
    expect(screen.getByText("排行範圍：已收錄個股")).toBeInTheDocument();
  });

  it("點擊週 tab → 切換內容並更新 aria-pressed", () => {
    renderRanking(makeMovers());
    fireEvent.click(screen.getByRole("button", { name: "週" }));
    expect(screen.getByRole("button", { name: "週" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByText("聯發科")).toBeInTheDocument();
  });

  it("空 tab → 顯示佔位", () => {
    renderRanking(makeMovers());
    fireEvent.click(screen.getByRole("button", { name: "月" }));
    expect(screen.getByText("此期間暫無排行資料")).toBeInTheDocument();
  });
});
