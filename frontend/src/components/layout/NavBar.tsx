import { NavLink } from "react-router-dom";

// 產業地圖無獨立頁，係依題材呈現（/topic/{slug}/map）；導覽列指向主要 seed 題材
// （矽光子）的地圖作為入口。若日後種子題材調整，同步更新此 slug。
const PRIMARY_TOPIC_SLUG = "silicon-photonics";

// 導覽項目：切片 7 起全項啟用（AI 分析上線；產業地圖指向主要題材地圖）。
const NAV_ITEMS = [
  { label: "每日焦點", to: "/", enabled: true },
  { label: "題材總覽", to: "/topics", enabled: true },
  { label: "產業地圖", to: `/topic/${PRIMARY_TOPIC_SLUG}/map`, enabled: true },
  { label: "公司資料庫", to: "/companies", enabled: true },
  { label: "AI 分析", to: "/ai", enabled: true },
] as const;

/** 頂部導覽列：深色底、indigo 主色 active 底線 */
export function NavBar() {
  return (
    <header className="sticky top-0 z-10 border-b border-border-line bg-surface">
      <nav className="mx-auto flex max-w-6xl items-center gap-6 px-6 h-14">
        <span className="font-semibold tracking-tight text-text-main">
          AI 智慧產業地圖
        </span>
        <ul className="flex items-center gap-1">
          {NAV_ITEMS.map((item) =>
            item.enabled ? (
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
            ) : (
              <li key={item.to}>
                <span
                  title="開發中"
                  aria-disabled="true"
                  className="inline-block cursor-not-allowed px-3 py-2 text-sm text-text-dim opacity-50"
                >
                  {item.label}
                </span>
              </li>
            ),
          )}
        </ul>
      </nav>
    </header>
  );
}
