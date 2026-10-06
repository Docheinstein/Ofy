import { Clock3, Disc, Play, Volume2 } from "lucide-react";
import type { TrackRowData } from "@/lib/api";
import { useLiveTrack } from "@/lib/live";
import { usePlayer } from "@/lib/player";
import { cn, formatDuration } from "@/lib/utils";
import { LyricsIndicator, TrackStatusButton } from "./StatusIcons";
import { SyncToggle } from "./SyncToggle";

interface Props {
  releaseId: string;
  artistId: string | null;
  albumTitle: string;
  tracks: TrackRowData[];
  onPlay: (index: number) => void;
  onOpen: (t: TrackRowData) => void;
  onDownload: (t: TrackRowData) => void;
  onRetry: (t: TrackRowData) => void;
}

export function TrackList({ releaseId, artistId, albumTitle, tracks, onPlay, onOpen, onDownload, onRetry }: Props) {
  const multiDisc = tracks.some((t) => t.disc_total > 1);
  let lastDisc = 0;
  return (
    <div className="px-6" data-testid="tracklist">
      <div className="grid grid-cols-[2.5rem_1fr_2rem_3.5rem_2.5rem_2rem] items-center gap-3 border-b px-4 pb-2 text-xs uppercase tracking-wider text-muted-foreground">
        <span className="text-right">#</span>
        <span>Title</span>
        <span />
        <span className="flex justify-end"><Clock3 className="h-4 w-4" /></span>
        <span />
        <span />
      </div>
      <div className="mt-2">
        {tracks.map((t, i) => {
          const header = multiDisc && t.disc !== lastDisc;
          lastDisc = t.disc;
          return (
            <div key={t.track_id}>
              {header && (
                <div className="mt-4 flex items-center gap-2 px-4 py-2 text-sm font-bold text-muted-foreground">
                  <Disc className="h-4 w-4" /> Disc {t.disc}
                  {t.medium_title ? ` — ${t.medium_title}` : ""}
                </div>
              )}
              <Row
                t={t}
                releaseId={releaseId}
                artistId={artistId}
                albumTitle={albumTitle}
                onPlay={() => onPlay(i)}
                onOpen={() => onOpen(t)}
                onDownload={() => onDownload(t)}
                onRetry={() => onRetry(t)}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Row({ t, releaseId, artistId, albumTitle, onPlay, onOpen, onDownload, onRetry }: {
  t: TrackRowData; releaseId: string; artistId: string | null; albumTitle: string; onPlay: () => void; onOpen: () => void; onDownload: () => void; onRetry: () => void;
}) {
  const live = useLiveTrack(t.track_id);
  const s = { ...t.library, ...(live ?? {}) };
  const { current, playing } = usePlayer();
  const isCurrent = current?.track_id === t.track_id || (!current?.track_id && current?.recording_id === t.recording_id);
  return (
    <div
      className="group grid cursor-pointer grid-cols-[2.5rem_1fr_2rem_3.5rem_2.5rem_2rem] items-center gap-3 rounded-md px-4 py-2 hover:bg-elevated"
      onClick={onOpen}
      onDoubleClick={onPlay}
      data-track-id={t.track_id}
      data-status={s.status}
    >
      <div className="flex justify-end text-sm tabular-nums text-muted-foreground">
        <span className={cn("group-hover:hidden", isCurrent && "text-primary")}>
          {isCurrent && playing ? <Volume2 className="h-4 w-4" /> : t.position}
        </span>
        <button
          className="hidden text-foreground group-hover:block"
          onClick={(e) => { e.stopPropagation(); onPlay(); }}
          aria-label="Play"
        >
          <Play className="h-4 w-4 fill-current" />
        </button>
      </div>
      <div className="min-w-0">
        <div className={cn("truncate text-[15px]", isCurrent && "text-primary")}>{t.title}</div>
        <div className="truncate text-sm text-muted-foreground">{t.artist}</div>
      </div>
      <div className="flex justify-center"><LyricsIndicator status={s.lyrics_status} /></div>
      <div className="text-right text-sm tabular-nums text-muted-foreground">{formatDuration(t.length_ms)}</div>
      <div className="flex justify-center">
        <TrackStatusButton
          status={s.status}
          progress={s.progress}
          stage={s.stage}
          error={s.error}
          onDownload={onDownload}
          onRetry={onRetry}
          onReview={onOpen}
        />
      </div>
      <SyncToggle
        target={{ kind: "track", id: t.track_id, title: t.title, subtitle: `${t.artist} — ${albumTitle}` }}
        artistId={artistId}
        releaseId={releaseId}
        hideWhenOff
      />
    </div>
  );
}
