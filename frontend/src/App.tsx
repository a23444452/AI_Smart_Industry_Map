import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { NavBar } from "./components/layout/NavBar";
import { TopicsPage } from "./pages/TopicsPage";

// 全域 React Query 客戶端
const queryClient = new QueryClient();

/** 應用外殼：Query Provider + Router + 導覽列 + 路由 */
function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <NavBar />
        <main>
          <Routes>
            <Route path="/" element={<Navigate to="/topics" replace />} />
            <Route path="/topics" element={<TopicsPage />} />
          </Routes>
        </main>
      </BrowserRouter>
    </QueryClientProvider>
  );
}

export default App;
