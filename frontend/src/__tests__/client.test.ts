import { describe, it, expect, vi, afterEach } from "vitest";
import { fetchJson, ApiError, API_BASE } from "../api/client";

/** 以 vi.stubGlobal 模擬 fetch 回應 */
function stubFetch(status: number, body: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchJson / ApiError", () => {
  it("非 2xx throw ApiError 且帶 status（呼叫端以狀態碼判斷，不解析字串）", async () => {
    stubFetch(404, { detail: "topic not found" });
    const err = await fetchJson("/api/topics/nope").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(404);
  });

  it("slug 含 404 的 500 錯誤不會被誤判為 404（status 為 500）", async () => {
    stubFetch(500, { error: { message: "伺服器發生錯誤" } });
    const err = await fetchJson("/api/topics/topic-404").catch(
      (e: unknown) => e,
    );
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(500);
  });

  it("解析巢狀 error.message（後端全域 handler 格式）", async () => {
    stubFetch(500, { error: { code: "internal", message: "伺服器發生錯誤" } });
    const err = await fetchJson("/api/x").catch((e: unknown) => e);
    expect((err as ApiError).message).toBe("API 500: 伺服器發生錯誤");
  });

  it("解析頂層 detail（FastAPI 慣例）", async () => {
    stubFetch(404, { detail: "找不到題材" });
    const err = await fetchJson("/api/x").catch((e: unknown) => e);
    expect((err as ApiError).message).toBe("API 404: 找不到題材");
  });

  it("body 無可用訊息時 message 帶路徑", async () => {
    stubFetch(502, {});
    const err = await fetchJson("/api/x").catch((e: unknown) => e);
    expect((err as ApiError).message).toBe("API 502: /api/x");
  });

  it("2xx 回傳解析後 JSON 並打到 API_BASE", async () => {
    stubFetch(200, { ok: true });
    const data = await fetchJson<{ ok: boolean }>("/api/x");
    expect(data).toEqual({ ok: true });
    expect(vi.mocked(fetch)).toHaveBeenCalledWith(`${API_BASE}/api/x`);
  });
});
