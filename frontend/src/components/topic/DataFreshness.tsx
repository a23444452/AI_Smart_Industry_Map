interface DataFreshnessProps {
  /** 最近成功更新時間（帶 Z 的 UTC ISO string），null 表示尚無資料 */
  lastSuccessAt: string | null;
  /** 資料可能過時（例如 pipeline job last_status === "stale"） */
  stale?: boolean;
}

/** 將 UTC ISO 時間格式化為台北時區 HH:mm（解析失敗回 null）。 */
function taipeiTime(iso: string): string | null {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleTimeString("zh-TW", {
    timeZone: "Asia/Taipei",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** 「資料更新於 HH:mm」小字；stale 時轉黃色並附「資料可能過時」。 */
export function DataFreshness({ lastSuccessAt, stale = false }: DataFreshnessProps) {
  const time = lastSuccessAt !== null ? taipeiTime(lastSuccessAt) : null;
  const color = stale ? "text-amber-400" : "text-text-dim";
  return (
    <span className={`text-xs ${color}`}>
      資料更新於 {time ?? "—"}
      {stale && <span className="text-amber-400">（資料可能過時）</span>}
    </span>
  );
}
