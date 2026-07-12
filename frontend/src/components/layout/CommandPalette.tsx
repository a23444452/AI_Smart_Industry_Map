import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useSearch } from "../../api/search";
import type { SearchCompany, SearchTopic } from "../../api/search";

/** 命令面板一列（扁平化兩組後供鍵盤連續導航）。 */
type FlatItem =
  | { kind: "company"; data: SearchCompany }
  | { kind: "topic"; data: SearchTopic };

/** 由結果列導出目的路徑：公司 → /c/{ticker}、題材 → /topic/{slug}。 */
function itemPath(item: FlatItem): string {
  return item.kind === "company"
    ? `/c/${item.data.ticker}`
    : `/topic/${item.data.slug}`;
}

const DEBOUNCE_MS = 200;

/**
 * 全域 ⌘K／Ctrl+K 快捷鍵：按下時 preventDefault 並開啟面板。
 * 於掛載時註冊 window keydown、卸載時移除（cleanup）——卸載後不再觸發。
 * @returns { open, setOpen } 面板開關狀態與 setter
 */
export function useCommandPalette() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen(true);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  return { open, setOpen };
}

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
}

/**
 * 全站命令面板（⌘K）：置中卡片 + 搜尋框（debounce 200ms → useSearch），
 * 結果分「公司」「題材」兩組、鍵盤上下連續導航、Enter/點擊前往、Esc/遮罩關閉。
 *
 * 注意 hooks 順序：所有 hook 恆呼叫，僅在 return 前依 open 決定是否渲染，
 * 避免同一實例 open 切換時 hook 數量變動（違反 Rules of Hooks）。
 */
export function CommandPalette({ open, onClose }: CommandPaletteProps) {
  const navigate = useNavigate();
  const [input, setInput] = useState("");
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  // 輸入 debounce 200ms → 更新查詢字串（避免逐字打字狂發請求）。
  useEffect(() => {
    const timer = setTimeout(() => setQuery(input), DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [input]);

  const { data } = useSearch(query);

  // 兩組結果扁平化為單一序列，供上下鍵連續移動 active。
  const items = useMemo<FlatItem[]>(() => {
    if (!data) return [];
    return [
      ...data.companies.map((c) => ({ kind: "company", data: c }) as const),
      ...data.topics.map((t) => ({ kind: "topic", data: t }) as const),
    ];
  }, [data]);

  // 結果變動時 active 歸零，避免索引越界。
  useEffect(() => {
    setActiveIndex(0);
  }, [items]);

  // 開啟時清空前次輸入、歸零 active 並聚焦輸入框。
  useEffect(() => {
    if (open) {
      setInput("");
      setQuery("");
      setActiveIndex(0);
      inputRef.current?.focus();
    }
  }, [open]);

  // 開啟時鎖住 body 捲動（關閉或卸載時還原）。
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  if (!open) return null;

  function select(item: FlatItem) {
    navigate(itemPath(item));
    onClose();
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Escape") {
      e.preventDefault();
      onClose();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((i) => Math.min(items.length - 1, i + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => Math.max(0, i - 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const item = items[activeIndex];
      if (item) select(item);
    }
  }

  const trimmed = query.trim();
  const companyCount = data?.companies.length ?? 0;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 pt-24"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="全站搜尋"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={onKeyDown}
        className="w-full max-w-lg overflow-hidden rounded-xl border border-border-line bg-surface shadow-2xl"
      >
        <input
          ref={inputRef}
          type="search"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="輸入代號、公司或題材名稱"
          aria-label="搜尋"
          autoFocus
          className="w-full border-b border-border-line bg-transparent px-4 py-3 text-sm text-text-main placeholder:text-text-dim focus:outline-none"
        />

        <div className="max-h-80 overflow-y-auto py-2" role="listbox">
          {trimmed.length === 0 ? (
            <p className="px-4 py-6 text-center text-sm text-text-dim">
              輸入代號、公司或題材名稱
            </p>
          ) : items.length === 0 ? (
            <p className="px-4 py-6 text-center text-sm text-text-dim">
              找不到符合項目
            </p>
          ) : (
            <>
              {companyCount > 0 && (
                <Group title="公司">
                  {data!.companies.map((c, i) => (
                    <Row
                      key={`c-${c.ticker}`}
                      active={activeIndex === i}
                      onSelect={() => select({ kind: "company", data: c })}
                      primary={c.ticker}
                      secondary={c.name}
                      tag={c.market}
                    />
                  ))}
                </Group>
              )}
              {data!.topics.length > 0 && (
                <Group title="題材">
                  {data!.topics.map((t, i) => (
                    <Row
                      key={`t-${t.slug}`}
                      active={activeIndex === companyCount + i}
                      onSelect={() => select({ kind: "topic", data: t })}
                      primary={t.title}
                      secondary={t.slug}
                    />
                  ))}
                </Group>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="px-2">
      <p className="px-2 py-1 text-xs font-medium text-text-dim">{title}</p>
      {children}
    </div>
  );
}

interface RowProps {
  active: boolean;
  onSelect: () => void;
  primary: string;
  secondary: string;
  tag?: string;
}

function Row({ active, onSelect, primary, secondary, tag }: RowProps) {
  return (
    <button
      type="button"
      role="option"
      aria-selected={active}
      onClick={onSelect}
      className={[
        "flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-sm transition-colors",
        active ? "bg-surface-2 text-text-main" : "text-text-dim hover:bg-surface-2",
      ].join(" ")}
    >
      <span className="font-medium text-text-main">{primary}</span>
      <span className="truncate text-text-dim">{secondary}</span>
      {tag && (
        <span className="ml-auto shrink-0 text-xs text-text-dim">{tag}</span>
      )}
    </button>
  );
}
