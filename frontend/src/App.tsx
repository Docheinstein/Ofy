import { Navigate, Route, Routes } from "react-router-dom";
import { Sidebar } from "@/components/Sidebar";
import { SettingsPage } from "@/pages/SettingsPage";

export default function App() {
  return (
    <div className="flex h-full flex-col gap-2 bg-black p-2">
      <div className="flex min-h-0 flex-1 gap-2">
        <Sidebar />
        <main className="min-w-0 flex-1 overflow-y-auto rounded-lg bg-surface">
          <Routes>
            <Route path="/" element={<Navigate to="/search" replace />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="*" element={<div className="p-8 text-muted-foreground">Coming soon</div>} />
          </Routes>
        </main>
      </div>
    </div>
  );
}
