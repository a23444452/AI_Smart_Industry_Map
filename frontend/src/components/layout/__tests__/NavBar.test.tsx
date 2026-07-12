import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NavBar } from "../NavBar";
import type { TopicsResponse } from "../../../api/topics";

// 以指定的 React Query 快取渲染 NavBar（NavBar 純讀 ["topics","tw","up"] 快取）。
function renderNav(opts: { seed?: TopicsResponse; onOpenSearch?: () => void } = {}) {
  const queryClient = new QueryClient();
  if (opts.seed) {
    queryClient.setQueryData(["topics", "tw", "up"], opts.seed);
  }
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <NavBar onOpenSearch={opts.onOpenSearch ?? (() => {})} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function makeTopics(slug: string): TopicsResponse {
  return {
    topics: [
      {
        slug,
        title: "測試題材",
        description: null,
        market_tab: "tw",
        company_count: 1,
        verified_at: null,
        change_pct_avg: null,
      },
    ],
    rank: [],
  };
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
    expect(document.querySelector('[aria-disabled="true"]')).toBeNull();
  });

  it("AI 分析連往 /ai", () => {
    renderNav();
    expect(screen.getByRole("link", { name: "AI 分析" })).toHaveAttribute(
      "href",
      "/ai",
    );
  });

  it("產業地圖 href：有題材快取 → 指向首列 slug（P3）", () => {
    renderNav({ seed: makeTopics("ai-server") });
    expect(screen.getByRole("link", { name: "產業地圖" })).toHaveAttribute(
      "href",
      "/topic/ai-server/map",
    );
  });

  it("產業地圖 href：無快取 → fallback silicon-photonics（P3）", () => {
    renderNav();
    expect(screen.getByRole("link", { name: "產業地圖" })).toHaveAttribute(
      "href",
      "/topic/silicon-photonics/map",
    );
  });

  it("點擊搜尋按鈕觸發 onOpenSearch", () => {
    const onOpenSearch = vi.fn();
    renderNav({ onOpenSearch });
    fireEvent.click(screen.getByRole("button", { name: "搜尋" }));
    expect(onOpenSearch).toHaveBeenCalledTimes(1);
  });
});
