// 後端 API 基底位址（可由 VITE_API_BASE 覆寫），預設為本機後端
export const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

/**
 * 取得 JSON 回應；非 2xx 時 throw 帶 HTTP 狀態碼的 Error。
 * @param path 以 / 開頭的 API 路徑，例如 "/api/topics?market=tw"
 */
export async function fetchJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) {
    throw new Error(`API ${res.status}: ${path}`);
  }
  return (await res.json()) as T;
}
