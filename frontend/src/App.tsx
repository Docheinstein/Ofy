import { useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { Sidebar } from "@/components/Sidebar";
import { LyricsPanel, PlayerBar } from "@/components/PlayerBar";
import { PlayerProvider } from "@/lib/player";
import { useLiveUpdates } from "@/lib/live";
import { SearchPage } from "@/pages/SearchPage";
import { ArtistPage } from "@/pages/ArtistPage";
import { AlbumPage } from "@/pages/AlbumPage";
import { LibraryPage } from "@/pages/LibraryPage";
import { DownloadsPage } from "@/pages/DownloadsPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { SyncPage } from "@/pages/SyncPage";

export default function App() {
  useLiveUpdates();
  const [lyricsOpen, setLyricsOpen] = useState(false);
  return (
    <PlayerProvider>
      <div className="flex h-full flex-col gap-2 bg-black p-2">
        <div className="flex min-h-0 flex-1 gap-2">
          <Sidebar />
          <main className="min-w-0 flex-1 overflow-y-auto rounded-lg bg-surface">
            <Routes>
              <Route path="/" element={<Navigate to="/search" replace />} />
              <Route path="/search" element={<SearchPage />} />
              <Route path="/artist/:id" element={<ArtistPage />} />
              <Route path="/album/:id" element={<AlbumPage />} />
              <Route path="/library" element={<LibraryPage />} />
              <Route path="/downloads" element={<DownloadsPage />} />
              <Route path="/sync" element={<SyncPage />} />
              <Route path="/settings" element={<SettingsPage />} />
              <Route path="*" element={<Navigate to="/search" replace />} />
            </Routes>
          </main>
          {lyricsOpen && <LyricsPanel />}
        </div>
        <PlayerBar lyricsOpen={lyricsOpen} onToggleLyrics={() => setLyricsOpen(!lyricsOpen)} />
      </div>
    </PlayerProvider>
  );
}
