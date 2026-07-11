import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ChipSignals } from "../ChipSignals";
import type { ChipSignalsData } from "../../../api/topicDetail";

function makeData(overrides: Partial<ChipSignalsData> = {}): ChipSignalsData {
  return {
    window_days: 5,
    total: 17,
    foreign_buy: 5,
    trust_buy: 6,
    major_buy: null,
    updated_at: "2026-07-11T11:26:58Z",
    ...overrides,
  };
}

describe("ChipSignals", () => {
  it("外資顯示 買超家數/總數（外資 5/17）", () => {
    render(<ChipSignals data={makeData()} />);
    expect(screen.getByText(/外資/)).toBeInTheDocument();
    expect(screen.getByText("5/17")).toBeInTheDocument();
  });

  it("投信顯示 6/17", () => {
    render(<ChipSignals data={makeData({ trust_buy: 6 })} />);
    expect(screen.getByText(/投信/)).toBeInTheDocument();
    expect(screen.getByText("6/17")).toBeInTheDocument();
  });

  it("大戶為 null 時顯示 —", () => {
    render(<ChipSignals data={makeData({ major_buy: null })} />);
    expect(screen.getByText(/大戶/)).toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("副標含「近 5 個交易日」", () => {
    render(<ChipSignals data={makeData({ window_days: 5 })} />);
    expect(screen.getByText(/近 5 個交易日/)).toBeInTheDocument();
  });
});
