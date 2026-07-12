import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { TriggerPanel } from "../TriggerPanel";

describe("TriggerPanel", () => {
  it("輸入 ticker、選 mode、送出 → onSubmit(ticker, mode)", () => {
    const onSubmit = vi.fn();
    render(<TriggerPanel onSubmit={onSubmit} isPending={false} errorDetail={null} />);

    fireEvent.change(screen.getByLabelText("股票代號"), {
      target: { value: "2330" },
    });
    fireEvent.change(screen.getByLabelText("分析模式"), {
      target: { value: "中期展望" },
    });
    fireEvent.click(screen.getByRole("button", { name: "開始分析" }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit).toHaveBeenCalledWith("2330", "中期展望");
  });

  it("ticker 空白時不呼叫 onSubmit（trim 後為空）", () => {
    const onSubmit = vi.fn();
    render(<TriggerPanel onSubmit={onSubmit} isPending={false} errorDetail={null} />);
    fireEvent.click(screen.getByRole("button", { name: "開始分析" }));
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("isPending 為 true → 按鈕與輸入 disabled、文案改為分析中", () => {
    render(<TriggerPanel onSubmit={vi.fn()} isPending errorDetail={null} />);
    expect(screen.getByRole("button")).toBeDisabled();
    expect(screen.getByLabelText("股票代號")).toBeDisabled();
    expect(screen.getByRole("button")).toHaveTextContent("分析中");
  });

  it("errorDetail（409 後端訊息）→ 顯示於面板", () => {
    render(
      <TriggerPanel
        onSubmit={vi.fn()}
        isPending={false}
        errorDetail="該個股同模式分析進行中，請稍候"
      />,
    );
    expect(
      screen.getByText("該個股同模式分析進行中，請稍候"),
    ).toBeInTheDocument();
  });
});
