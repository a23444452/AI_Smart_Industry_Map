// 後端 API 基底位址（可由 VITE_API_BASE 覆寫），預設為本機後端
export const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

/** 帶 HTTP 狀態碼的 API 錯誤：呼叫端以 status 判斷（如 404），不解析 message 字串。 */
export class ApiError extends Error {
  readonly status: number;
  /** 後端原始錯誤訊息（不含 "API {status}:" 前綴），無則 null。供 UI 直接顯示。 */
  readonly detail: string | null;

  constructor(message: string, status: number, detail: string | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
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
  if (!res.ok) await throwApiError(res, path);
  return (await res.json()) as T;
}

/**
 * 送出 JSON body 的 POST 並取回 JSON 回應；非 2xx 時 throw ApiError（帶 status 與
 * 後端 detail，如 409）。呼叫端以 status 分流、以 detail 顯示後端訊息。
 * @param path 以 / 開頭的 API 路徑
 * @param body 會序列化為 JSON 的請求主體
 */
export async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) await throwApiError(res, path);
  return (await res.json()) as T;
}

/** 由非 2xx 回應建構並拋出 ApiError（帶 status 與後端 detail）。 */
async function throwApiError(res: Response, path: string): Promise<never> {
  const detail = await readErrorMessage(res);
  throw new ApiError(
    detail ? `API ${res.status}: ${detail}` : `API ${res.status}: ${path}`,
    res.status,
    detail,
  );
}
