import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MopsTimeline } from "../MopsTimeline";
import type { AnnouncementItem } from "../../../api/daily";
import * as dailyApi from "../../../api/daily";

// MopsTimeline 自接 useAnnouncements，故 mock 該模組（保留其餘 export）。
vi.mock("../../../api/daily", async () => {
  const actual = await vi.importActual<typeof dailyApi>("../../../api/daily");
  return { ...actual, useAnnouncements: vi.fn() };
});

const mockUseAnnouncements = vi.mocked(dailyApi.useAnnouncements);

function announcement(overrides: Partial<AnnouncementItem> = {}): AnnouncementItem {
  return {
    ticker: "2330",
    name: "台積電",
    category: "重大事件",
    title: "本公司代子公司公告重大訊息",
    published_at: "2026-07-11T01:30:00Z",
    ...overrides,
  };
}

function result(overrides: Record<string, unknown>) {
  return {
    data: undefined,
    isLoading: false,
    ...overrides,
  } as unknown as ReturnType<typeof dailyApi.useAnnouncements>;
}

const DATES = ["2026-07-11", "2026-07-10"];

describe("MopsTimeline", () => {
  beforeEach(() => mockUseAnnouncements.mockReset());

  it("日期 tabs：第一個為 active，且以第一日、category=null 呼叫 hook", () => {
    mockUseAnnouncements.mockReturnValue(result({ data: [announcement()] }));
    render(<MopsTimeline dates={DATES} />);
    expect(screen.getByRole("button", { name: "07-11" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(mockUseAnnouncements).toHaveBeenCalledWith("2026-07-11", null);
  });

  it("公告卡：分類 chip、標題、代號名稱與台北時間", () => {
    mockUseAnnouncements.mockReturnValue(result({ data: [announcement()] }));
    render(<MopsTimeline dates={DATES} />);
    // 分類同時出現在 chip 與卡片，用 getAllByText 斷言存在
    expect(screen.getAllByText("重大事件").length).toBeGreaterThan(0);
    expect(
      screen.getByText("本公司代子公司公告重大訊息"),
    ).toBeInTheDocument();
    expect(screen.getByText(/2330/)).toBeInTheDocument();
    // 01:30 UTC → 台北 09:30
    expect(screen.getByText(/09:30/)).toBeInTheDocument();
  });

  it("點分類 chip「自結」→ 以該分類重呼 hook", () => {
    mockUseAnnouncements.mockReturnValue(result({ data: [] }));
    render(<MopsTimeline dates={DATES} />);
    fireEvent.click(screen.getByRole("button", { name: "自結" }));
    expect(mockUseAnnouncements).toHaveBeenLastCalledWith("2026-07-11", "自結");
  });

  it("切換日期 tab → 以該日重呼 hook", () => {
    mockUseAnnouncements.mockReturnValue(result({ data: [] }));
    render(<MopsTimeline dates={DATES} />);
    fireEvent.click(screen.getByRole("button", { name: "07-10" }));
    expect(mockUseAnnouncements).toHaveBeenLastCalledWith("2026-07-10", null);
  });

  it("loading 態顯示載入中", () => {
    mockUseAnnouncements.mockReturnValue(result({ isLoading: true }));
    render(<MopsTimeline dates={DATES} />);
    expect(screen.getByText("載入中…")).toBeInTheDocument();
  });

  it("空資料顯示此日暫無公告", () => {
    mockUseAnnouncements.mockReturnValue(result({ data: [] }));
    render(<MopsTimeline dates={DATES} />);
    expect(screen.getByText("此日暫無公告")).toBeInTheDocument();
  });

  it("dates 為空 → 顯示近期暫無公告", () => {
    mockUseAnnouncements.mockReturnValue(result({ data: undefined }));
    render(<MopsTimeline dates={[]} />);
    expect(screen.getByText("近期暫無公告")).toBeInTheDocument();
  });
});
