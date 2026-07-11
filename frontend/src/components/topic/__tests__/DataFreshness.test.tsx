import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { DataFreshness } from "../DataFreshness";

describe("DataFreshness", () => {
  it("顯示「資料更新於」＋台北時間（11:26Z → 19:26，zh-TW locale 輸出 下午07:26）", () => {
    render(<DataFreshness lastSuccessAt="2026-07-11T11:26:58Z" />);
    // zh-TW 預設 12 小時制：19:26 台北 → 「下午07:26」（含分鐘 07:26）。
    expect(screen.getByText(/資料更新於/)).toBeInTheDocument();
    expect(screen.getByText(/07:26/)).toBeInTheDocument();
  });

  it("stale 為 true 時帶黃色提示樣式與「資料可能過時」字樣", () => {
    render(<DataFreshness lastSuccessAt="2026-07-11T11:26:58Z" stale />);
    expect(screen.getByText(/資料可能過時/)).toBeInTheDocument();
    const el = screen.getByText(/資料可能過時/);
    expect(el.className).toMatch(/amber/);
  });

  it("lastSuccessAt 為 null 時顯示 —", () => {
    render(<DataFreshness lastSuccessAt={null} />);
    expect(screen.getByText(/—/)).toBeInTheDocument();
  });
});
