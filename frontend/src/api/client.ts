// 後端 API 基底位址（可由 VITE_API_BASE 覆寫），預設為本機後端
export const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

/** 帶 HTTP 狀態碼的 API 錯誤：呼叫端以 status 判斷（如 404），不解析 message 字串。 */
export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/**
 * 嘗試從錯誤回應 body 取出訊息，失敗回 null。支援兩種格式：
 * - 巢狀 `{"error": {"message": ...}}`（後端全域 exception handler 實際格式）
 * - 頂層 `{"detail": ...}` / `{"message": ...}`（FastAPI 慣例）
 */
async function readErrorMessage(res: Response): Promise<string | null> {
  try {
    const body: unknown = await res.json();
    if (!body || typeof body !== "object") return null;
    const record = body as Record<string, unknown>;
    // 巢狀格式優先（後端 error handler）
    if (record.error && typeof record.error === "object") {
      const nested = (record.error as Record<string, unknown>).message;
      if (typeof nested === "string" && nested.length > 0) return nested;
    }
    const msg = record.detail ?? record.message;
    if (typeof msg === "string" && msg.length > 0) return msg;
    return null;
  } catch {
    return null;
  }
}

/**
 * 取得 JSON 回應；非 2xx 時 throw ApiError（帶 HTTP status 與後端錯誤訊息，若有）。
 * @param path 以 / 開頭的 API 路徑，例如 "/api/topics?market=tw"
 */
export async function fetchJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) {
    const detail = await readErrorMessage(res);
    throw new ApiError(
      detail ? `API ${res.status}: ${detail}` : `API ${res.status}: ${path}`,
      res.status,
    );
  }
  return (await res.json()) as T;
}
