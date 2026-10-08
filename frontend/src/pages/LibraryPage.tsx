import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, Disc, ExternalLink, Loader2, MicVocal, Play, RefreshCw, Search, User, Volume2, X } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, coverUrl, type LibraryAlbum, type LibraryTrack } from "@/lib/api";
import { ArtistAvatar } from "@/components/ArtistAvatar";
import { Button } from "@/components/ui/button";
import { Cover } from "@/components/Cover";
import { Input } from "@/components/ui/input";
import { LyricsIndicator } from "@/components/StatusIcons";
import { SyncToggle } from "@/components/SyncToggle";
import { usePlayer } from "@/lib/player";
import { useSyncSelection } from "@/lib/sync";
import { cn, formatDuration } from "@/lib/utils";

type SyncFilter = "all" | "synced" | "unsynced";

const SYNC_FILTERS: { value: SyncFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "synced", label: "Synced" },
  { value: "unsynced", label: "Not synced" },
];

/** Which artists and albums are unfolded; kept for the tab so going back from an album restores the tree.
 * While searching, nodes leading to a match start unfolded instead; folding one lasts until the search changes. */
function useExpanded(q: string) {
  const [open, setOpen] = useState<Set<string>>(() => {
    try {
      return new Set(JSON.parse(sessionStorage.getItem("library-open") ?? "[]") as string[]);
    } catch {
      return new Set();
    }
  });
  const toggle = (key: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (!next.delete(key)) next.add(key);
      try {
        sessionStorage.setItem("library-open", JSON.stringify([...next]));
      } catch {
        /* not persisted */
      }
      return next;
    });
  const [flipped, setFlipped] = useState<{ q: string; keys: Set<string> }>({ q, keys: new Set() });
  const flippedKeys = flipped.q === q ? flipped.keys : new Set<string>();
  const flip = (key: string) => {
    const next = new Set(flippedKeys);
    if (!next.delete(key)) next.add(key);
    setFlipped({ q, keys: next });
  };
  return {
    isOpen: (key: string, revealed: boolean) => (revealed ? !flippedKeys.has(key) : open.has(key)),
    toggle: (key: string, revealed: boolean) => (revealed ? flip(key) : toggle(key)),
  };
}

export function LibraryPage() {
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  // ?sync=synced|unsynced, kept in the URL so it survives going back from an album or artist
  const syncParam = params.get("sync");
  const filter: SyncFilter = syncParam === "synced" || syncParam === "unsynced" ? syncParam : "all";
  const setFilter = (f: SyncFilter) => {
    const next = new URLSearchParams(params);
    if (f === "all") next.delete("sync");
    else next.set("sync", f);
    setParams(next, { replace: true });
  };
  // ?q= narrows the tree to matching artists, albums and songs
  const q = params.get("q") ?? "";
  const needle = q.trim().toLowerCase();
  const setQuery = (v: string) => {
    const next = new URLSearchParams(params);
    if (v) next.set("q", v);
    else next.delete("q");
    setParams(next, { replace: true });
  };
  const sel = useSyncSelection();
  const expanded = useExpanded(needle);
  const { data, isLoading } = useQuery({ queryKey: ["library"], queryFn: () => api.get<LibraryAlbum[]>("/api/library/albums") });
  const rescan = useMutation({
    mutationFn: () => api.post<{ changed: number }>("/api/library/rescan"),
    onSuccess: () => qc.invalidateQueries(),
  });
  const lyrics = useMutation({ mutationFn: () => api.post<{ queued: number }>("/api/library/lyrics") });

  // Synced is decided per song: picked on its own, or brought along by its album or artist.
  const isSynced = (a: LibraryAlbum, t: LibraryTrack) =>
    sel.has("track", t.track_id) || sel.has("album", a.release_id) || sel.has("artist", a.artist_id);
  const matches = (text: string) => text.toLowerCase().includes(needle);
  // The search first: a matching artist or album brings all its songs, otherwise only the matching songs remain.
  const searched: Shown[] = (data ?? []).flatMap((a): Shown[] => {
    if (!needle || matches(a.artist)) return [{ album: a, songs: a.tracks, reveal: "none" }];
    if (matches(a.title)) return [{ album: a, songs: a.tracks, reveal: "artist" }];
    const songs = a.tracks.filter((t) => matches(t.title));
    return songs.length ? [{ album: a, songs, reveal: "album" }] : [];
  });
  const counts: Record<SyncFilter, number> = { all: 0, synced: 0, unsynced: 0 };
  for (const { album: a, songs } of searched) {
    for (const t of songs) {
      counts.all++;
      counts[isSynced(a, t) ? "synced" : "unsynced"]++;
    }
  }
  // Then the sync filter: each album keeps only the songs matching it, so one album can show up under both.
  const albums: Shown[] = searched
    .map((s) => ({ ...s, songs: filter === "all" ? s.songs : s.songs.filter((t) => isSynced(s.album, t) === (filter === "synced")) }))
    .filter((s) => (filter === "all" && s.songs === s.album.tracks) || s.songs.length > 0);
  const groups = groupByArtist(albums);

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
      <div className="relative mb-4 max-w-xl">
        <Search className="absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={q}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Escape" && setQuery("")}
          placeholder="Filter artists, albums and songs"
          className="h-10 rounded-full border-none bg-elevated pl-11 pr-10"
          data-testid="library-search"
        />
        {q && (
          <button
            type="button"
            onClick={() => setQuery("")}
            aria-label="Clear filter"
            className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>
      <div className="mb-4 flex flex-wrap gap-2" role="group" aria-label="Filter songs by sync state">
        {SYNC_FILTERS.map(({ value, label }) => (
          <button
            key={value}
            type="button"
            onClick={() => setFilter(value)}
            aria-pressed={filter === value}
            data-testid={`sync-filter-${value}`}
            className={cn(
              "rounded-full px-3 py-1 text-sm font-semibold transition-colors",
              filter === value ? "bg-foreground text-background" : "bg-elevated text-foreground hover:bg-elevated/70",
            )}
          >
            {label} {data && <span className="font-normal opacity-60">{counts[value]}</span>}
          </button>
        ))}
      </div>
      {isLoading && <Loader2 className="animate-spin" />}
      {data && data.length === 0 && <p className="text-muted-foreground">Nothing here yet. Search for an album and download it.</p>}
      {data && data.length > 0 && searched.length === 0 && (
        <p className="text-muted-foreground">Nothing in the library matches “{q.trim()}”.</p>
      )}
      {searched.length > 0 && groups.length === 0 && (
        <p className="text-muted-foreground">
          {filter === "synced"
            ? `No ${needle ? "matching " : ""}songs are selected for sync yet.`
            : `Every ${needle ? "matching" : "downloaded"} song is selected for sync.`}
        </p>
      )}
      <div className="flex flex-col" data-testid="library-tree">
        {groups.map((g) => (
          <ArtistNode key={g.key} group={g} filtered={filter !== "all" || !!needle} expanded={expanded} />
        ))}
      </div>
    </div>
  );
}

/** An album as shown under the current filters: only its matching songs. */
interface Shown {
  album: LibraryAlbum;
  songs: LibraryTrack[];
  /** How far the tree unfolds by itself to show what the search matched. */
  reveal: "none" | "artist" | "album";
}

interface Group {
  key: string;
  artist: string;
  artistId: string | null;
  albums: Shown[];
}

type Expanded = ReturnType<typeof useExpanded>;

/** Albums arrive sorted by artist → year → title; bucket them by artist, keeping that order. */
function groupByArtist(albums: Shown[]): Group[] {
  const groups = new Map<string, Group>();
  for (const s of albums) {
    const a = s.album;
    const key = a.artist_id ?? `name:${a.artist.toLowerCase()}`;
    let g = groups.get(key);
    if (!g) groups.set(key, (g = { key, artist: a.artist, artistId: a.artist_id, albums: [] }));
    g.albums.push(s);
  }
  return [...groups.values()];
}

const plural = (n: number, word: string) => `${n} ${n === 1 ? word : `${word}s`}`;

function Caret({ open }: { open: boolean }) {
  return <ChevronRight className={cn("h-5 w-5 shrink-0 text-muted-foreground transition-transform", open && "rotate-90")} />;
}

function Avatar({ group: g, className }: { group: Group; className: string }) {
  return g.artistId ? (
    <ArtistAvatar id={g.artistId} fallbackRg={g.albums[0].album.release_group_id} className={`${className} shrink-0`} />
  ) : (
    <div className={`${className} flex shrink-0 items-center justify-center rounded-full bg-elevated text-muted-foreground shadow-lg`}>
      <User className="h-1/3 w-1/3" />
    </div>
  );
}

/** An artist; unfolding it lists their albums right below. */
function ArtistNode({ group: g, filtered, expanded }: { group: Group; filtered: boolean; expanded: Expanded }) {
  const revealed = g.albums.some((s) => s.reveal !== "none");
  const open = expanded.isOpen(g.key, revealed);
  const songs = g.albums.reduce((n, s) => n + s.songs.length, 0);
  return (
    <section data-testid="library-artist">
      <div className="group flex items-center gap-2 rounded-md pr-3 transition-colors hover:bg-elevated">
        <button
          type="button"
          onClick={() => expanded.toggle(g.key, revealed)}
          aria-expanded={open}
          className="flex min-w-0 flex-1 items-center gap-3 px-3 py-2 text-left"
          data-testid="library-artist-row"
        >
          <Caret open={open} />
          <Avatar group={g} className="h-12 w-12" />
          <div className="min-w-0 flex-1">
            <div className="truncate font-semibold">{g.artist}</div>
            <div className="text-sm text-muted-foreground">
              {plural(g.albums.length, "album")} • {plural(songs, "song")}
            </div>
          </div>
        </button>
        {g.artistId && (
          <>
            <SyncToggle target={{ kind: "artist", id: g.artistId, title: g.artist, subtitle: "Artist" }} hideWhenOff />
            <Link
              to={`/artist/${g.artistId}`}
              aria-label={`Open ${g.artist}`}
              title="Open artist page"
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-muted-foreground opacity-0 transition-opacity hover:text-foreground focus-visible:opacity-100 group-hover:opacity-100"
            >
              <ExternalLink className="h-4 w-4" />
            </Link>
          </>
        )}
      </div>
      {open && (
        <div className="ml-6 border-l pl-2">
          {g.albums.map((s) => (
            <AlbumNode key={s.album.release_id} shown={s} filtered={filtered} expanded={expanded} />
          ))}
        </div>
      )}
    </section>
  );
}

/** An album under its artist; unfolding it lists its downloaded songs (only those matching the filter). */
function AlbumNode({ shown: { album: a, songs, reveal }, filtered, expanded }: { shown: Shown; filtered: boolean; expanded: Expanded }) {
  const key = `album:${a.release_id}`;
  const open = expanded.isOpen(key, reveal === "album");
  const detail = filtered
    ? plural(songs.length, "song")
    : `${a.library.done}/${a.library.total} tracks`;
  return (
    <div data-testid="library-album" data-release-id={a.release_id}>
      <div className="group flex items-center gap-2 rounded-md pr-3 transition-colors hover:bg-elevated">
        <button
          type="button"
          onClick={() => expanded.toggle(key, reveal === "album")}
          aria-expanded={open}
          className="flex min-w-0 flex-1 items-center gap-3 px-3 py-2 text-left"
          data-testid="library-album-row"
        >
          <Caret open={open} />
          <Cover src={coverUrl("release", a.release_id, 250, a.release_group_id)} alt={a.title} className="h-10 w-10 shrink-0" rounded="rounded" />
          <div className="min-w-0 flex-1">
            <div className="truncate font-medium">{a.title}</div>
            <div className="text-sm text-muted-foreground">{[a.year, detail].filter(Boolean).join(" • ")}</div>
          </div>
        </button>
        <SyncToggle target={{ kind: "album", id: a.release_id, title: a.title, subtitle: a.artist }} artistId={a.artist_id} hideWhenOff />
        <Link
          to={`/album/${a.release_group_id}`}
          aria-label={`Open ${a.title}`}
          title="Open album page"
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-muted-foreground opacity-0 transition-opacity hover:text-foreground focus-visible:opacity-100 group-hover:opacity-100"
        >
          <ExternalLink className="h-4 w-4" />
        </Link>
      </div>
      {open && (
        <div className="ml-8 border-l pl-2">
          {songs.length === 0 && <p className="px-3 py-2 text-sm text-muted-foreground">No songs downloaded yet.</p>}
          <SongList album={a} songs={songs} />
        </div>
      )}
    </div>
  );
}

function SongList({ album: a, songs }: { album: LibraryAlbum; songs: LibraryTrack[] }) {
  const player = usePlayer();
  const multiDisc = songs.some((t) => t.disc !== songs[0].disc);
  const playFrom = (i: number) =>
    player.playList(
      songs.map((t) => ({
        recording_id: t.recording_id,
        track_id: t.track_id,
        release_id: a.release_id,
        title: t.title,
        artist: t.artist,
        length_ms: t.length_ms,
        cover: coverUrl("release", a.release_id, 250, a.release_group_id),
      })),
      i,
    );
  let lastDisc = 0;
  return (
    <>
      {songs.map((t, i) => {
        const header = multiDisc && t.disc !== lastDisc;
        lastDisc = t.disc;
        return (
          <div key={t.track_id}>
            {header && (
              <div className="flex items-center gap-2 px-3 pb-1 pt-3 text-xs font-bold text-muted-foreground">
                <Disc className="h-3.5 w-3.5" /> Disc {t.disc}
              </div>
            )}
            <SongRow album={a} t={t} onPlay={() => playFrom(i)} />
          </div>
        );
      })}
    </>
  );
}

function SongRow({ album: a, t, onPlay }: { album: LibraryAlbum; t: LibraryTrack; onPlay: () => void }) {
  const { current, playing } = usePlayer();
  const isCurrent = current?.track_id === t.track_id;
  return (
    <div
      className="group grid grid-cols-[2rem_1fr_1.5rem_3.5rem_2rem] items-center gap-3 rounded-md px-3 py-1.5 hover:bg-elevated"
      onDoubleClick={onPlay}
      data-testid="library-song"
      data-track-id={t.track_id}
    >
      <div className="flex justify-end text-sm tabular-nums text-muted-foreground">
        <span className={cn("group-hover:hidden", isCurrent && "text-primary")}>
          {isCurrent && playing ? <Volume2 className="h-4 w-4" /> : t.position}
        </span>
        <button className="hidden text-foreground group-hover:block" onClick={onPlay} aria-label={`Play ${t.title}`}>
          <Play className="h-4 w-4 fill-current" />
        </button>
      </div>
      <div className="min-w-0">
        <div className={cn("truncate text-[15px]", isCurrent && "text-primary")}>{t.title}</div>
        {t.artist !== a.artist && <div className="truncate text-sm text-muted-foreground">{t.artist}</div>}
      </div>
      <div className="flex justify-center"><LyricsIndicator status={t.lyrics_status} /></div>
      <div className="text-right text-sm tabular-nums text-muted-foreground">{formatDuration(t.length_ms)}</div>
      <SyncToggle
        target={{ kind: "track", id: t.track_id, title: t.title, subtitle: `${t.artist} — ${a.title}` }}
        artistId={a.artist_id}
        releaseId={a.release_id}
        hideWhenOff
      />
    </div>
  );
}
