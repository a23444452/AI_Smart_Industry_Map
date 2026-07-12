import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  render,
  screen,
  fireEvent,
  act,
  renderHook,
} from "@testing-library/react";
import { CommandPalette, useCommandPalette } from "../CommandPalette";
import type { SearchResponse } from "../../../api/search";
import * as searchApi from "../../../api/search";

// mock useSearch：不打真實網路，回傳可控結果；navigate 以 mock 監看目的路徑。
vi.mock("../../../api/search", async () => {
  const actual = await vi.importActual<typeof searchApi>("../../../api/search");
  return { ...actual, useSearch: vi.fn() };
});

const mockNavigate = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual =
    await vi.importActual<typeof import("react-router-dom")>(
      "react-router-dom",
    );
  return { ...actual, useNavigate: () => mockNavigate };
});

const mockUseSearch = vi.mocked(searchApi.useSearch);

function setResult(data: SearchResponse | undefined) {
  mockUseSearch.mockReturnValue({
    data,
  } as unknown as ReturnType<typeof searchApi.useSearch>);
}

const SAMPLE: SearchResponse = {
  companies: [{ ticker: "2330", name: "台積電", market: "上市" }],
  topics: [{ slug: "silicon-photonics", title: "矽光子" }],
};

/** 輸入關鍵字並推進 debounce（200ms）→ query 生效、結果渲染。 */
function typeQuery(value: string) {
  const input = screen.getByLabelText("搜尋");
  act(() => {
    fireEvent.change(input, { target: { value } });
  });
  act(() => {
    vi.advanceTimersByTime(200);
  });
}

describe("CommandPalette", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mockUseSearch.mockReset();
    mockNavigate.mockReset();
    setResult(undefined);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("open=true 時輸入框 autofocus 且容器為 role=dialog", () => {
    render(<CommandPalette open onClose={() => {}} />);
    const dialog = screen.getByRole("dialog");
    expect(dialog).toBeInTheDocument();
    expect(document.activeElement).toBe(screen.getByLabelText("搜尋"));
  });

  it("q 為空時顯示提示；空結果顯示找不到符合項目", () => {
    setResult({ companies: [], topics: [] });
    render(<CommandPalette open onClose={() => {}} />);
    // 尚未輸入 → 提示文案
    expect(
      screen.getByText("輸入代號、公司或題材名稱", { selector: "p" }),
    ).toBeInTheDocument();
    // 輸入後空結果 → 找不到
    typeQuery("zzz");
    expect(screen.getByText("找不到符合項目")).toBeInTheDocument();
  });

  it("輸入後渲染「公司」「題材」分組標題與項目", () => {
    setResult(SAMPLE);
    render(<CommandPalette open onClose={() => {}} />);
    typeQuery("台");
    expect(screen.getByText("公司")).toBeInTheDocument();
    expect(screen.getByText("題材")).toBeInTheDocument();
    expect(screen.getByText("2330")).toBeInTheDocument();
    expect(screen.getByText("矽光子")).toBeInTheDocument();
  });

  it("↑↓ 跨組連續移動 active（aria-selected）", () => {
    setResult(SAMPLE);
    render(<CommandPalette open onClose={() => {}} />);
    typeQuery("台");
    const dialog = screen.getByRole("dialog");
    const options = screen.getAllByRole("option");
    // 初始 active 為第一項（公司）
    expect(options[0]).toHaveAttribute("aria-selected", "true");
    expect(options[1]).toHaveAttribute("aria-selected", "false");
    // ↓ 跨到第二項（題材）
    act(() => {
      fireEvent.keyDown(dialog, { key: "ArrowDown" });
    });
    expect(screen.getAllByRole("option")[1]).toHaveAttribute(
      "aria-selected",
      "true",
    );
    // ↑ 回到第一項
    act(() => {
      fireEvent.keyDown(dialog, { key: "ArrowUp" });
    });
    expect(screen.getAllByRole("option")[0]).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("Enter 前往 active 項路徑並關閉（公司 /c、題材 /topic）", () => {
    setResult(SAMPLE);
    const onClose = vi.fn();
    render(<CommandPalette open onClose={onClose} />);
    typeQuery("台");
    const dialog = screen.getByRole("dialog");
    // active 第一項（公司 2330）→ /c/2330
    act(() => {
      fireEvent.keyDown(dialog, { key: "Enter" });
    });
    expect(mockNavigate).toHaveBeenCalledWith("/c/2330");
    expect(onClose).toHaveBeenCalledTimes(1);
    // 移到題材再 Enter → /topic/silicon-photonics
    act(() => {
      fireEvent.keyDown(dialog, { key: "ArrowDown" });
    });
    act(() => {
      fireEvent.keyDown(dialog, { key: "Enter" });
    });
    expect(mockNavigate).toHaveBeenCalledWith("/topic/silicon-photonics");
  });

  it("Esc 關閉面板", () => {
    setResult(SAMPLE);
    const onClose = vi.fn();
    render(<CommandPalette open onClose={onClose} />);
    act(() => {
      fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("點擊項目 → 前往並關閉", () => {
    setResult(SAMPLE);
    const onClose = vi.fn();
    render(<CommandPalette open onClose={onClose} />);
    typeQuery("矽");
    act(() => {
      fireEvent.click(screen.getByText("矽光子"));
    });
    expect(mockNavigate).toHaveBeenCalledWith("/topic/silicon-photonics");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("open=false 時不渲染", () => {
    setResult(SAMPLE);
    render(<CommandPalette open={false} onClose={() => {}} />);
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

describe("useCommandPalette 全域快捷鍵", () => {
  it("⌘K 與 Ctrl+K 皆開啟面板", () => {
    const { result } = renderHook(() => useCommandPalette());
    expect(result.current.open).toBe(false);
    act(() => {
      window.dispatchEvent(
        new KeyboardEvent("keydown", { key: "k", metaKey: true }),
      );
    });
    expect(result.current.open).toBe(true);

    act(() => {
      result.current.setOpen(false);
    });
    expect(result.current.open).toBe(false);
    act(() => {
      window.dispatchEvent(
        new KeyboardEvent("keydown", { key: "k", ctrlKey: true }),
      );
    });
    expect(result.current.open).toBe(true);
  });

  it("卸載後移除 listener（cleanup），不再觸發", () => {
    const removeSpy = vi.spyOn(window, "removeEventListener");
    const { result, unmount } = renderHook(() => useCommandPalette());
    unmount();
    expect(removeSpy).toHaveBeenCalledWith("keydown", expect.any(Function));
    // 卸載後派發事件不應影響先前狀態（listener 已移除）
    act(() => {
      window.dispatchEvent(
        new KeyboardEvent("keydown", { key: "k", metaKey: true }),
      );
    });
    expect(result.current.open).toBe(false);
    removeSpy.mockRestore();
  });
});
