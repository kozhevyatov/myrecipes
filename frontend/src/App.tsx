import type { ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Layout } from "@/components/Layout";
import { FullScreenLoader } from "@/components/FullScreenLoader";
import SetupPage from "@/pages/SetupPage";
import LoginPage from "@/pages/LoginPage";
import RegisterPage from "@/pages/RegisterPage";
import HomePage from "@/pages/HomePage";
import AdminPage from "@/pages/AdminPage";
import RecipePage from "@/pages/RecipePage";
import RecipeEditPage from "@/pages/RecipeEditPage";

function RequireAuth({ children, admin = false }: { children: ReactNode; admin?: boolean }) {
  const { user } = useAuth();
  const location = useLocation();
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  if (admin && !user.is_admin) return <Navigate to="/" replace />;
  return <>{children}</>;
}

export default function App() {
  const { ready } = useAuth();
  const location = useLocation();
  const status = useQuery({ queryKey: ["setup-status"], queryFn: api.setup.status });

  if (status.isLoading || !ready) return <FullScreenLoader />;
  if (status.isError)
    return <FullScreenLoader error="Не удалось связаться с сервером. Проверьте, что контейнер запущен." />;

  const setupDone = status.data?.setup_complete;
  if (!setupDone && location.pathname !== "/setup") return <Navigate to="/setup" replace />;

  return (
    <Routes>
      <Route path="/setup" element={setupDone ? <Navigate to="/" replace /> : <SetupPage />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route element={<Layout />}>
        <Route
          index
          element={
            <RequireAuth>
              <HomePage />
            </RequireAuth>
          }
        />
        <Route
          path="/recipes/new"
          element={
            <RequireAuth>
              <RecipeEditPage />
            </RequireAuth>
          }
        />
        <Route
          path="/recipes/:id"
          element={
            <RequireAuth>
              <RecipePage />
            </RequireAuth>
          }
        />
        <Route
          path="/recipes/:id/edit"
          element={
            <RequireAuth>
              <RecipeEditPage />
            </RequireAuth>
          }
        />
        <Route
          path="/admin"
          element={
            <RequireAuth admin>
              <AdminPage />
            </RequireAuth>
          }
        />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
