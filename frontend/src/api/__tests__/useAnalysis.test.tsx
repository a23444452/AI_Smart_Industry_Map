import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useAnalysis, POLL_TIMEOUT_MS, type AnalysisDetail } from "../ai";
import * as client from "../client";

// mock fetchJson：不打真實網路，回傳可控的 AnalysisDetail。
vi.mock("../client", async () => {
  const actual = await vi.importActual<typeof client>("../client");
  return { ...actual, fetchJson: vi.fn() };
});

const mockFetchJson = vi.mocked(client.fetchJson);

function pendingDetail(): AnalysisDetail {
  return {
    id: 1,
    ticker: "2330",
    name: "台積電",
    mode: "全面檢視",
    status: "pending",
    scores: null,
    reasons: null,
    summary: null,
    total: null,
    model: null,
    error: null,
    created_at: "2026-07-12T00:00:00Z",
  };
}

describe("useAnalysis：逾時與 restart 恢復輪詢", () => {
  let queryClient: QueryClient;
  let now: number;

  beforeEach(() => {
    now = 1_000_000_000;
    vi.spyOn(Date, "now").mockImplementation(() => now);
    // vi.restoreAllMocks 不會清 module mock 的呼叫紀錄，逐測試手動 reset。
    mockFetchJson.mockReset();
    mockFetchJson.mockResolvedValue(pendingDetail());
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
  });

  afterEach(() => {
    queryClient.clear();
    vi.restoreAllMocks();
  });

  function wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
  }

  it("進行中未逾時 → timedOut 為 false；超過上限 → true；restart() 後解除並 refetch", async () => {
    const { result, rerender } = renderHook(() => useAnalysis(1), { wrapper });

    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(result.current.data?.status).toBe("pending");
    expect(result.current.timedOut).toBe(false);

    // 模擬時間超過輪詢上限 → timedOut 轉為 true（輪詢安全網已停）
    now += POLL_TIMEOUT_MS + 1_000;
    rerender();
    expect(result.current.timedOut).toBe(true);

    // 重試：restart() 重置起始 timestamp 並 refetch → timedOut 解除、恢復輪詢
    const callsBefore = mockFetchJson.mock.calls.length;
    act(() => {
      result.current.restart();
    });
    rerender();
    expect(result.current.timedOut).toBe(false);
    await waitFor(() =>
      expect(mockFetchJson.mock.calls.length).toBeGreaterThan(callsBefore),
    );
  });

  it("id 為 null → 查詢停用，不發請求", () => {
    renderHook(() => useAnalysis(null), { wrapper });
    expect(mockFetchJson).not.toHaveBeenCalled();
  });
});
