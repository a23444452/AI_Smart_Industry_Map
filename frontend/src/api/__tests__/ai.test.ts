import { describe, it, expect } from "vitest";
import {
  analysisRefetchInterval,
  shouldRefreshLeaderboard,
  POLL_INTERVAL_MS,
  POLL_TIMEOUT_MS,
} from "../ai";

describe("analysisRefetchInterval", () => {
  it("pending 且未逾時 → 每 POLL_INTERVAL_MS 輪詢", () => {
    expect(analysisRefetchInterval("pending", 0)).toBe(POLL_INTERVAL_MS);
    expect(analysisRefetchInterval("pending", 30_000)).toBe(POLL_INTERVAL_MS);
  });

  it("running 且未逾時 → 每 POLL_INTERVAL_MS 輪詢", () => {
    expect(analysisRefetchInterval("running", 10_000)).toBe(POLL_INTERVAL_MS);
  });

  it("進行中但已達輪詢上限 → false（停止輪詢安全網）", () => {
    expect(analysisRefetchInterval("pending", POLL_TIMEOUT_MS)).toBe(false);
    expect(analysisRefetchInterval("running", POLL_TIMEOUT_MS + 5_000)).toBe(
      false,
    );
  });

  it("done/failed/undefined → 不輪詢（false）", () => {
    expect(analysisRefetchInterval("done", 0)).toBe(false);
    expect(analysisRefetchInterval("failed", 0)).toBe(false);
    expect(analysisRefetchInterval(undefined, 0)).toBe(false);
  });
});

describe("shouldRefreshLeaderboard（分析完成 → 排行榜刷新判斷）", () => {
  it("轉為 done 的瞬間 → true（pending/running/undefined → done）", () => {
    expect(shouldRefreshLeaderboard("pending", "done")).toBe(true);
    expect(shouldRefreshLeaderboard("running", "done")).toBe(true);
    // 首次抓取即為 done（如 mock 秒回）亦視為剛完成
    expect(shouldRefreshLeaderboard(undefined, "done")).toBe(true);
  });

  it("已是 done 或非 done 結果 → false（不重複 invalidate）", () => {
    expect(shouldRefreshLeaderboard("done", "done")).toBe(false);
    expect(shouldRefreshLeaderboard("pending", "running")).toBe(false);
    expect(shouldRefreshLeaderboard("running", "failed")).toBe(false);
    expect(shouldRefreshLeaderboard(undefined, undefined)).toBe(false);
  });
});
