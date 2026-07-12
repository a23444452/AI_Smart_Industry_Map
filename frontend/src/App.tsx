import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { ApiError } from "./api/client";
import { NavBar } from "./components/layout/NavBar";
import {
  CommandPalette,
  useCommandPalette,
} from "./components/layout/CommandPalette";
import { DailyPage } from "./pages/DailyPage";
import { TopicsPage } from "./pages/TopicsPage";
import { TopicDetailPage } from "./pages/TopicDetailPage";
import { TopicMapPage } from "./pages/TopicMapPage";
import { CompaniesPage } from "./pages/CompaniesPage";
import { CompanyPage } from "./pages/CompanyPage";
import { AiPage } from "./pages/AiPage";

// 全域 React Query 客戶端：30 秒內視為新鮮、切回視窗不自動重抓。
// retry：4xx 為明確的客戶端錯誤（如 404）不重試、立即進錯誤態；其餘（5xx／網路）重試 1 次。
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: (failureCount, error) => {
        if (
          error instanceof ApiError &&
          error.status >= 400 &&
          error.status < 500
        ) {
          return false;
        }
        return failureCount < 1;
      },
      refetchOnWindowFocus: false,
    },
  },
});

/** 應用外殼：Query Provider + Router + 導覽列 + 路由 + ⌘K 命令面板 */
function App() {
  // ⌘K 開關狀態掛在 App 層：NavBar 搜尋按鈕與全域快捷鍵共用，CommandPalette
  // 掛在 BrowserRouter 內側（useNavigate 需要 Router context）。
  const { open, setOpen } = useCommandPalette();
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <NavBar onOpenSearch={() => setOpen(true)} />
        <CommandPalette open={open} onClose={() => setOpen(false)} />
        <main>
          <Routes>
            <Route path="/" element={<DailyPage />} />
            <Route path="/topics" element={<TopicsPage />} />
            <Route path="/topic/:slug" element={<TopicDetailPage />} />
            <Route path="/topic/:slug/map" element={<TopicMapPage />} />
            <Route path="/companies" element={<CompaniesPage />} />
            <Route path="/c/:ticker" element={<CompanyPage />} />
            <Route path="/ai" element={<AiPage />} />
          </Routes>
        </main>
      </BrowserRouter>
    </QueryClientProvider>
  );
}

export default App;
