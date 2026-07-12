import { useQueryClient } from "@tanstack/react-query";
import { NavLink } from "react-router-dom";
import type { TopicsResponse } from "../../api/topics";

// 產業地圖無獨立頁，係依題材呈現（/topic/{slug}/map）；無快取時的後備 seed 題材
// （矽光子）。若日後種子題材調整，同步更新此 slug。
const FALLBACK_TOPIC_SLUG = "silicon-photonics";

interface NavBarProps {
  /** 點擊搜尋按鈕時開啟命令面板（由 App 傳入）。 */
  onOpenSearch: () => void;
}

/** 頂部導覽列：深色底、indigo 主色 active 底線；含 ⌘K 搜尋入口 */
export function NavBar({ onOpenSearch }: NavBarProps) {
  const queryClient = useQueryClient();

  // 產業地圖入口動態指向題材總覽首列（tw/up 排行首項）：純讀 React Query 快取，
  // 不另發請求（getQueryData 不觸發 re-render——快取更新後首次 re-render 才反映，
  // 尚無快取則用後備 slug，皆為可接受的漸進顯示）。
  const topicsCache = queryClient.getQueryData<TopicsResponse>([
    "topics",
    "tw",
    "up",
  ]);
  const mapSlug = topicsCache?.topics[0]?.slug ?? FALLBACK_TOPIC_SLUG;

  const navItems = [
    { label: "每日焦點", to: "/" },
    { label: "題材總覽", to: "/topics" },
    { label: "產業地圖", to: `/topic/${mapSlug}/map` },
    { label: "公司資料庫", to: "/companies" },
    { label: "AI 分析", to: "/ai" },
  ] as const;

  return (
    <header className="sticky top-0 z-10 border-b border-border-line bg-surface">
      <nav className="mx-auto flex max-w-6xl items-center gap-6 px-6 h-14">
        <span className="font-semibold tracking-tight text-text-main">
          AI 智慧產業地圖
        </span>
        <ul className="flex items-center gap-1">
          {navItems.map((item) => (
            <li key={item.to}>
              <NavLink
                to={item.to}
                end={item.to === "/"}
                className={({ isActive }) =>
                  [
                    "inline-block px-3 py-2 text-sm transition-colors",
                    "border-b-2",
                    isActive
                      ? "border-accent text-text-main"
                      : "border-transparent text-text-dim hover:text-text-main",
                  ].join(" ")
                }
              >
                {item.label}
              </NavLink>
            </li>
          ))}
        </ul>

        {/* ⌘K 搜尋入口：點擊開啟命令面板；灰字提示 + 鍵帽 chip */}
        <button
          type="button"
          onClick={onOpenSearch}
          aria-label="搜尋"
          className="ml-auto flex items-center gap-2 rounded-lg border border-border-line bg-surface px-3 py-1.5 text-sm text-text-dim transition-colors hover:text-text-main"
        >
          <span>搜尋…</span>
          <kbd className="rounded border border-border-line px-1.5 py-0.5 text-xs text-text-dim">
            ⌘K
          </kbd>
        </button>
      </nav>
    </header>
  );
}
