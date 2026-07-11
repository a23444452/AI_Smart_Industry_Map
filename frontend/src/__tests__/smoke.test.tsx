import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import App from "../App";

// 冒煙測試：確認 App 能渲染並掛上導覽列的「題材總覽」入口
describe("App shell", () => {
  it("renders the topics nav entry", () => {
    render(<App />);
    expect(screen.getByText("題材總覽")).toBeInTheDocument();
  });
});
