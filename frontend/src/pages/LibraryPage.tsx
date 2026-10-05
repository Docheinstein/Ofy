import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, MicVocal, RefreshCw } from "lucide-react";
import { useState } from "react";
import { api, type LibraryAlbum } from "@/lib/api";
import { AlbumCard } from "@/components/AlbumCard";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";

export function LibraryPage() {
  const qc = useQueryClient();
  const [filter, setFilter] = useState<"all" | "complete" | "partial">("all");
  const { data, isLoading } = useQuery({ queryKey: ["library"], queryFn: () => api.get<LibraryAlbum[]>("/api/library/albums") });
  const rescan = useMutation({
    mutationFn: () => api.post<{ changed: number }>("/api/library/rescan"),
    onSuccess: () => qc.invalidateQueries(),
  });
  const lyrics = useMutation({ mutationFn: () => api.post<{ queued: number }>("/api/library/lyrics") });
  const albums = (data ?? []).filter((a) => filter === "all" || a.library.status === filter);

  return (
    <div className="p-6">
      <div className="mb-6 flex flex-wrap items-center gap-4">
        <h1 className="text-3xl font-extrabold">Your Library</h1>
        <div className="flex-1" />
        <Button variant="secondary" size="sm" onClick={() => lyrics.mutate()} disabled={lyrics.isPending}>
          {lyrics.isPending ? <Loader2 className="animate-spin" /> : <MicVocal />} Fetch missing lyrics
        </Button>
        <Button variant="secondary" size="sm" onClick={() => rescan.mutate()} disabled={rescan.isPending} data-testid="rescan">
          {rescan.isPending ? <Loader2 className="animate-spin" /> : <RefreshCw />} Rescan
        </Button>
      </div>
      {lyrics.data && <p className="mb-4 text-sm text-muted-foreground">Queued lyrics lookups for {lyrics.data.queued} tracks.</p>}
      {rescan.data && <p className="mb-4 text-sm text-muted-foreground">Rescan complete — {rescan.data.changed} changes.</p>}
      <Tabs value={filter} onValueChange={(v) => setFilter(v as typeof filter)} className="mb-4">
        <TabsList>
          <TabsTrigger value="all">All</TabsTrigger>
          <TabsTrigger value="complete">Complete</TabsTrigger>
          <TabsTrigger value="partial">Partial</TabsTrigger>
        </TabsList>
      </Tabs>
      {isLoading && <Loader2 className="animate-spin" />}
      {data && albums.length === 0 && <p className="text-muted-foreground">Nothing here yet. Search for an album and download it.</p>}
      <div className="grid grid-cols-[repeat(auto-fill,minmax(170px,1fr))] gap-1">
        {albums.map((a) => (
          <AlbumCard
            key={a.release_id}
            rg={{
              id: a.release_group_id,
              title: a.title,
              artist: a.artist,
              artist_id: a.artist_id,
              year: a.year,
              primary_type: null,
              secondary_types: [],
              first_release_date: null,
              library: a.library,
            }}
            subtitle={`${a.artist} • ${a.library.done}/${a.library.total}`}
          />
        ))}
      </div>
    </div>
  );
}
