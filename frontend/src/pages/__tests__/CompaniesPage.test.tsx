import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { CompaniesPage } from "../CompaniesPage";
import type { CompanyListResponse } from "../../api/companies";
import * as companiesApi from "../../api/companies";

// 直接 mock hook 模組，避免拉起 QueryClient；聚焦頁面的 debounce／篩選邏輯。
vi.mock("../../api/companies", async () => {
  const actual =
    await vi.importActual<typeof companiesApi>("../../api/companies");
  return { ...actual, useCompanies: vi.fn() };
});

const mockUseCompanies = vi.mocked(companiesApi.useCompanies);

function makeResponse(
  overrides: Partial<CompanyListResponse> = {},
): CompanyListResponse {
  return {
    total: 1,
    page: 1,
    page_size: 20,
    items: [
      {
        ticker: "2330",
        name: "台積電",
        market: "twse",
        topics: [],
        close: 1000,
        change_pct: 1.5,
        per: 20,
        revenue_yoy: 10,
      },
    ],
    topics_facets: [
      { slug: "ai", title: "AI 伺服器" },
      { slug: "silicon-photonics", title: "矽光子" },
    ],
    ...overrides,
  };
}

function queryResult(overrides: Record<string, unknown> = {}) {
  return {
    data: makeResponse(),
    isLoading: false,
    isError: false,
    isPlaceholderData: false,
    refetch: vi.fn(),
    ...overrides,
  } as unknown as ReturnType<typeof companiesApi.useCompanies>;
}

function renderPage() {
  return render(
    <MemoryRouter>
      <CompaniesPage />
    </MemoryRouter>,
  );
}

/** 取最後一次 useCompanies(query, topic, page) 的引數。 */
function lastArgs() {
  return mockUseCompanies.mock.calls.at(-1);
}

describe("CompaniesPage", () => {
  beforeEach(() => {
    mockUseCompanies.mockReset();
    mockUseCompanies.mockReturnValue(queryResult());
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("搜尋輸入經 300ms debounce 後才更新 query 參數", () => {
    renderPage();
    const input = screen.getByLabelText("搜尋代號或名稱");

    fireEvent.change(input, { target: { value: "2330" } });
    // 尚未到 300ms：query 仍為空字串
    expect(lastArgs()?.[0]).toBe("");

    act(() => {
      vi.advanceTimersByTime(299);
    });
    expect(lastArgs()?.[0]).toBe("");

    act(() => {
      vi.advanceTimersByTime(1);
    });
    // 滿 300ms：query 更新為輸入值
    expect(lastArgs()?.[0]).toBe("2330");
  });

  it("題材下拉改變即時觸發 useCompanies 的 topic 參數", () => {
    renderPage();
    const select = screen.getByLabelText("題材篩選");

    fireEvent.change(select, { target: { value: "ai" } });
    // 下拉無 debounce，立即反映到 topic（第二個參數）
    expect(lastArgs()?.[1]).toBe("ai");
  });

  it("渲染分頁摘要「第 X 頁·共 N 筆」", () => {
    mockUseCompanies.mockReturnValue(
      queryResult({ data: makeResponse({ total: 42 }) }),
    );
    renderPage();
    expect(screen.getByText("第 1 頁·共 42 筆")).toBeInTheDocument();
  });
});
