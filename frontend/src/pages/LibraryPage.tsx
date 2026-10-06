import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, LayoutGrid, List, Loader2, MicVocal, RefreshCw, User } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, type LibraryAlbum } from "@/lib/api";
import { AlbumCard } from "@/components/AlbumCard";
import { ArtistAvatar } from "@/components/ArtistAvatar";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";

type View = "grid" | "list";

function storedView(): View {
  try {
    return localStorage.getItem("library-view") === "list" ? "list" : "grid";
  } catch {
    return "grid";
  }
}

export function LibraryPage() {
  const qc = useQueryClient();
  const [filter, setFilter] = useState<"all" | "complete" | "partial">("all");
  const [params, setParams] = useSearchParams();
  // ?artist=<group key> narrows the page to one artist's albums (reached from the list view).
  const artistKey = params.get("artist");
  const view: View = (params.get("view") as View | null) ?? storedView();
  const setView = (v: View) => {
    try {
      localStorage.setItem("library-view", v);
    } catch {
      /* not persisted */
    }
    setParams({ view: v }, { replace: true });
  };
  const { data, isLoading } = useQuery({ queryKey: ["library"], queryFn: () => api.get<LibraryAlbum[]>("/api/library/albums") });
  const rescan = useMutation({
    mutationFn: () => api.post<{ changed: number }>("/api/library/rescan"),
    onSuccess: () => qc.invalidateQueries(),
  });
  const lyrics = useMutation({ mutationFn: () => api.post<{ queued: number }>("/api/library/lyrics") });
  const albums = (data ?? []).filter((a) => filter === "all" || a.library.status === filter);
  const groups = groupByArtist(albums);
  const selected = artistKey ? groups.filter((g) => g.key === artistKey) : null;

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
      <div className="mb-4 flex flex-wrap items-center gap-4">
        <Tabs value={filter} onValueChange={(v) => setFilter(v as typeof filter)}>
          <TabsList>
            <TabsTrigger value="all">All</TabsTrigger>
            <TabsTrigger value="complete">Complete</TabsTrigger>
            <TabsTrigger value="partial">Partial</TabsTrigger>
          </TabsList>
        </Tabs>
        <div className="flex-1" />
        {!selected && (
          <Tabs value={view} onValueChange={(v) => setView(v as View)}>
            <TabsList>
              <TabsTrigger value="grid" title="Albums by artist" aria-label="Grid view" data-testid="view-grid">
                <LayoutGrid className="h-4 w-4" />
              </TabsTrigger>
              <TabsTrigger value="list" title="Artists only" aria-label="List view" data-testid="view-list">
                <List className="h-4 w-4" />
              </TabsTrigger>
            </TabsList>
          </Tabs>
        )}
      </div>
      {isLoading && <Loader2 className="animate-spin" />}
      {data && albums.length === 0 && !selected && (
        <p className="text-muted-foreground">Nothing here yet. Search for an album and download it.</p>
      )}
      {selected ? (
        <>
          <Button variant="ghost" size="sm" className="mb-4" onClick={() => setParams({ view: "list" })} data-testid="back-to-artists">
            <ChevronLeft /> All artists
          </Button>
          {data && selected.length === 0 && <p className="text-muted-foreground">No albums for this artist match the filter.</p>}
          {selected.map((g) => (
            <ArtistGroup key={g.key} group={g} />
          ))}
        </>
      ) : view === "list" ? (
        <div className="flex flex-col" data-testid="library-artist-list">
          {groups.map((g) => (
            <ArtistRow key={g.key} group={g} onOpen={() => setParams({ view: "list", artist: g.key })} />
          ))}
        </div>
      ) : (
        <div className="flex flex-col gap-8">
          {groups.map((g) => (
            <ArtistGroup key={g.key} group={g} />
          ))}
        </div>
      )}
    </div>
  );
}

interface Group {
  key: string;
  artist: string;
  artistId: string | null;
  albums: LibraryAlbum[];
}

/** Albums arrive sorted by artist → year → title; bucket them by artist, keeping that order. */
function groupByArtist(albums: LibraryAlbum[]): Group[] {
  const groups = new Map<string, Group>();
  for (const a of albums) {
    const key = a.artist_id ?? `name:${a.artist.toLowerCase()}`;
    let g = groups.get(key);
    if (!g) groups.set(key, (g = { key, artist: a.artist, artistId: a.artist_id, albums: [] }));
    g.albums.push(a);
  }
  return [...groups.values()];
}

function Avatar({ group: g, className }: { group: Group; className: string }) {
  return g.artistId ? (
    <ArtistAvatar id={g.artistId} fallbackRg={g.albums[0].release_group_id} className={`${className} shrink-0`} />
  ) : (
    <div className={`${className} flex shrink-0 items-center justify-center rounded-full bg-elevated text-muted-foreground shadow-lg`}>
      <User className="h-1/3 w-1/3" />
    </div>
  );
}

function summary(g: Group) {
  const done = g.albums.reduce((n, a) => n + a.library.done, 0);
  const total = g.albums.reduce((n, a) => n + a.library.total, 0);
  return `${g.albums.length} ${g.albums.length === 1 ? "album" : "albums"} • ${done}/${total} tracks`;
}

/** One line of the list view: the artist only; clicking it shows that artist's albums. */
function ArtistRow({ group: g, onOpen }: { group: Group; onOpen: () => void }) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className="flex items-center gap-4 rounded-md px-3 py-2 text-left transition-colors hover:bg-elevated"
      data-testid="library-artist-row"
    >
      <Avatar group={g} className="h-12 w-12" />
      <div className="min-w-0 flex-1">
        <div className="truncate font-semibold">{g.artist}</div>
        <div className="text-sm text-muted-foreground">{summary(g)}</div>
      </div>
      <ChevronRight className="h-5 w-5 shrink-0 text-muted-foreground" />
    </button>
  );
}

function ArtistGroup({ group: g }: { group: Group }) {
  const avatar = <Avatar group={g} className="h-16 w-16" />;
  return (
    <section data-testid="library-artist">
      <div className="mb-2 flex items-center gap-4 px-3">
        {g.artistId ? <Link to={`/artist/${g.artistId}`}>{avatar}</Link> : avatar}
        <div className="min-w-0">
          {g.artistId ? (
            <Link to={`/artist/${g.artistId}`} className="block truncate text-xl font-bold hover:underline">{g.artist}</Link>
          ) : (
            <div className="truncate text-xl font-bold">{g.artist}</div>
          )}
          <div className="text-sm text-muted-foreground">{summary(g)}</div>
        </div>
      </div>
      <div className="grid grid-cols-[repeat(auto-fill,minmax(170px,1fr))] gap-1">
        {g.albums.map((a) => (
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
            subtitle={[a.year, `${a.library.done}/${a.library.total}`].filter(Boolean).join(" • ")}
          />
        ))}
      </div>
    </section>
  );
}
