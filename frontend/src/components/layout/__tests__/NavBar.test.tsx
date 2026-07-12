import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { NavBar } from "../NavBar";

function renderNav() {
  return render(
    <MemoryRouter>
      <NavBar />
    </MemoryRouter>,
  );
}

describe("NavBar", () => {
  it("五項導覽全部為可點連結（無開發中佔位）", () => {
    renderNav();
    for (const label of [
      "每日焦點",
      "題材總覽",
      "產業地圖",
      "公司資料庫",
      "AI 分析",
    ]) {
      expect(screen.getByRole("link", { name: label })).toBeInTheDocument();
    }
    // 不再有 aria-disabled 佔位項
    expect(document.querySelector('[aria-disabled="true"]')).toBeNull();
  });

  it("AI 分析連往 /ai", () => {
    renderNav();
    expect(screen.getByRole("link", { name: "AI 分析" })).toHaveAttribute(
      "href",
      "/ai",
    );
  });
});
