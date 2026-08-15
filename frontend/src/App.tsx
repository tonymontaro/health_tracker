import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./components/auth";
import { Layout } from "./components/Layout";
import { HistoryPage } from "./pages/HistoryPage";
import { InventoryPage } from "./pages/InventoryPage";
import { LoginPage } from "./pages/LoginPage";
import { SettingsPage } from "./pages/SettingsPage";
import { TodayPage } from "./pages/TodayPage";

function Protected() {
  const { session, loading } = useAuth();
  if (loading) return <div className="loading">Preparing your plan...</div>;
  if (!session) return <Navigate to="/login" replace />;
  return <Layout />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<Protected />}>
        <Route path="/today" element={<Navigate to="/today/food" replace />} />
        <Route path="/today/food" element={<TodayPage section="food" />} />
        <Route path="/today/exercise" element={<TodayPage section="exercise" />} />
        <Route path="/history" element={<Navigate to="/history/exercise" replace />} />
        <Route path="/history/nutrition" element={<HistoryPage section="nutrition" />} />
        <Route path="/history/exercise" element={<HistoryPage section="exercise" />} />
        <Route path="/inventory" element={<InventoryPage />} />
        <Route path="/shopping" element={<Navigate to="/inventory" replace />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/today/food" replace />} />
    </Routes>
  );
}
