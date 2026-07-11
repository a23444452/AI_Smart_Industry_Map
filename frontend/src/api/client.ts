// 後端 API 基底位址（可由 VITE_API_BASE 覆寫），預設為本機後端
export const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

/** 嘗試從錯誤回應 body 取出訊息（FastAPI 慣例 detail／通用 message），失敗回 null */
async function readErrorMessage(res: Response): Promise<string | null> {
  try {
    const body: unknown = await res.json();
    if (body && typeof body === "object") {
      const record = body as Record<string, unknown>;
      const msg = record.detail ?? record.message;
      if (typeof msg === "string" && msg.length > 0) return msg;
    }
    return null;
  } catch {
    return null;
  }
}

/**
 * 取得 JSON 回應；非 2xx 時 throw 帶 HTTP 狀態碼（與後端錯誤訊息，若有）的 Error。
 * @param path 以 / 開頭的 API 路徑，例如 "/api/topics?market=tw"
 */
export async function fetchJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) {
    const detail = await readErrorMessage(res);
    throw new Error(
      detail ? `API ${res.status}: ${detail}` : `API ${res.status}: ${path}`,
    );
  }
  return (await res.json()) as T;
}
