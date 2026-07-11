import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { TopicMapPage } from "../TopicMapPage";
import { ApiError } from "../../api/client";
import type { TopicMap } from "../../api/topicMap";
import * as topicMapApi from "../../api/topicMap";

// 直接 mock hook 模組，避免拉起 QueryClient/msw。
vi.mock("../../api/topicMap", async () => {
  const actual = await vi.importActual<typeof topicMapApi>("../../api/topicMap");
  return { ...actual, useTopicMap: vi.fn() };
});

const mockUseTopicMap = vi.mocked(topicMapApi.useTopicMap);

function makeMap(overrides: Partial<TopicMap> = {}): TopicMap {
  return {
    slug: "silicon-photonics",
    title: "矽光子",
    levels: [
      {
        level: "上游",
        categories: [
          {
            name: "矽光子晶片",
            desc: "光引擎核心",
            placeholder: false,
            companies: [
              {
                ticker: "2330",
                name: "台積電",
                role: "龍頭",
                relevance: "高",
                close: 1000,
                change_pct: 1.5,
                badges: [],
              },
            ],
          },
        ],
      },
      {
        level: "中游",
        categories: [
          { name: "封裝測試", desc: null, placeholder: true, companies: [] },
        ],
      },
    ],
    ...overrides,
  };
}

// useQuery 回傳形狀的最小替身
function queryResult(overrides: Record<string, unknown>) {
  return {
    data: undefined,
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
    ...overrides,
  } as unknown as ReturnType<typeof topicMapApi.useTopicMap>;
}

function renderPage(slug = "silicon-photonics") {
  return render(
    <MemoryRouter initialEntries={[`/topic/${slug}/map`]}>
      <Routes>
        <Route path="/topic/:slug/map" element={<TopicMapPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("TopicMapPage", () => {
  beforeEach(() => {
    mockUseTopicMap.mockReset();
  });

  it("正常態：渲染 title、副標與各層級區段", () => {
    mockUseTopicMap.mockReturnValue(queryResult({ data: makeMap() }));
    renderPage();

    expect(screen.getByRole("heading", { name: "矽光子" })).toBeInTheDocument();
    expect(screen.getByText("產業內部結構")).toBeInTheDocument();
    // 兩個層級標題
    expect(screen.getByText("上游")).toBeInTheDocument();
    expect(screen.getByText("中游")).toBeInTheDocument();
    // 分類與公司下探到子元件
    expect(screen.getByText("矽光子晶片")).toBeInTheDocument();
    expect(screen.getByText("台積電")).toBeInTheDocument();
    // 產業鏈 toggle 為 active，總覽為連回詳情頁的連結
    expect(
      screen.getByRole("link", { name: "總覽" }),
    ).toHaveAttribute("href", "/topic/silicon-photonics");
  });

  it("載入態：顯示 skeleton，不渲染標題", () => {
    mockUseTopicMap.mockReturnValue(queryResult({ isLoading: true }));
    renderPage();
    expect(screen.queryByRole("heading", { name: "矽光子" })).toBeNull();
  });

  it("404：顯示找不到此題材與回題材總覽連結", () => {
    mockUseTopicMap.mockReturnValue(
      queryResult({
        isError: true,
        error: new ApiError("not found", 404),
      }),
    );
    renderPage();
    expect(screen.getByText("找不到此題材")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "回題材總覽" }),
    ).toHaveAttribute("href", "/topics");
  });

  it("其他錯誤：顯示錯誤卡與重試按鈕", () => {
    mockUseTopicMap.mockReturnValue(
      queryResult({
        isError: true,
        error: new ApiError("server error", 500),
      }),
    );
    renderPage();
    expect(screen.getByText(/產業地圖載入失敗/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重試" })).toBeInTheDocument();
  });
});
