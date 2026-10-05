import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Loader2, MicVocal, Pause, Play, SkipBack, SkipForward, Volume1, Volume2, VolumeX } from "lucide-react";
import { api } from "@/lib/api";
import { usePlayer } from "@/lib/player";
import { parseLrc } from "@/lib/lrc";
import { cn, formatSeconds } from "@/lib/utils";
import { Slider } from "@/components/ui/slider";
import { Cover } from "./Cover";

interface LyricsResp {
  status: string;
  synced: string | null;
  plain: string | null;
}

export function PlayerBar({ lyricsOpen, onToggleLyrics }: { lyricsOpen: boolean; onToggleLyrics: () => void }) {
  const { current, audio, playing, setPlaying, toggle, next, prev, queue, index } = usePlayer();
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [volume, setVolume] = useState(() => Number(localStorage.getItem("volume") ?? 0.8));
  const [muted, setMuted] = useState(false);
  const [loading, setLoading] = useState(false);
  const [seeking, setSeeking] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    const a = audio.current;
    if (!a || !current) return;
    a.src = `/api/stream/${current.recording_id}${current.release_id ? `?release=${current.release_id}` : ""}`;
    setErr(null);
    setTime(0);
    setDuration((current.length_ms ?? 0) / 1000);
    if (playing) void a.play().catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current?.recording_id, current?.track_id]);

  useEffect(() => {
    if (audio.current) audio.current.volume = muted ? 0 : volume;
    localStorage.setItem("volume", String(volume));
  }, [volume, muted, audio]);

  const VolIcon = muted || volume === 0 ? VolumeX : volume < 0.5 ? Volume1 : Volume2;
  const shown = seeking ?? time;

  return (
    <footer className="grid h-20 shrink-0 grid-cols-[1fr_2fr_1fr] items-center gap-4 px-2">
      <audio
        ref={audio}
        preload="auto"
        onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
        onDurationChange={(e) => Number.isFinite(e.currentTarget.duration) && setDuration(e.currentTarget.duration)}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onWaiting={() => setLoading(true)}
        onCanPlay={() => setLoading(false)}
        onPlaying={() => setLoading(false)}
        onEnded={() => (index + 1 < queue.length ? next() : setPlaying(false))}
        onError={() => {
          setLoading(false);
          if (current) setErr("Playback failed");
        }}
        data-testid="audio"
      />
      <div className="flex min-w-0 items-center gap-3">
        {current && (
          <>
            <Cover src={current.cover} className="h-14 w-14 shrink-0" rounded="rounded" />
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold" data-testid="now-playing">{current.title}</div>
              <div className="truncate text-xs text-muted-foreground">{err ? <span className="text-destructive">{err}</span> : current.artist}</div>
            </div>
          </>
        )}
      </div>

      <div className="flex flex-col items-center gap-1.5">
        <div className="flex items-center gap-5">
          <button onClick={prev} disabled={!current} className="text-muted-foreground hover:text-foreground disabled:opacity-40" aria-label="Previous">
            <SkipBack className="h-5 w-5 fill-current" />
          </button>
          <button
            onClick={toggle}
            disabled={!current}
            className="flex h-9 w-9 items-center justify-center rounded-full bg-foreground text-background transition-transform hover:scale-105 disabled:opacity-40"
            aria-label={playing ? "Pause" : "Play"}
            data-testid="play-toggle"
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : playing ? <Pause className="h-4 w-4 fill-current" /> : <Play className="ml-0.5 h-4 w-4 fill-current" />}
          </button>
          <button onClick={next} disabled={!current || index + 1 >= queue.length} className="text-muted-foreground hover:text-foreground disabled:opacity-40" aria-label="Next">
            <SkipForward className="h-5 w-5 fill-current" />
          </button>
        </div>
        <div className="flex w-full max-w-xl items-center gap-2 text-[11px] tabular-nums text-muted-foreground">
          <span className="w-10 text-right">{formatSeconds(shown)}</span>
          <Slider
            value={[shown]}
            max={duration || 1}
            step={0.5}
            disabled={!current}
            onValueChange={([v]) => setSeeking(v)}
            onValueCommit={([v]) => {
              if (audio.current) audio.current.currentTime = v;
              setSeeking(null);
            }}
          />
          <span className="w-10">{formatSeconds(duration)}</span>
        </div>
      </div>

      <div className="flex items-center justify-end gap-3 pr-2">
        <button
          onClick={onToggleLyrics}
          className={cn("text-muted-foreground hover:text-foreground", lyricsOpen && "text-primary")}
          aria-label="Lyrics"
        >
          <MicVocal className="h-4 w-4" />
        </button>
        <button onClick={() => setMuted(!muted)} className="text-muted-foreground hover:text-foreground" aria-label="Mute">
          <VolIcon className="h-4 w-4" />
        </button>
        <Slider className="w-28" value={[muted ? 0 : volume]} max={1} step={0.01} onValueChange={([v]) => { setVolume(v); setMuted(false); }} />
      </div>
    </footer>
  );
}

export function LyricsPanel() {
  const { current, audio } = usePlayer();
  const { data } = useQuery({
    queryKey: ["lyrics", current?.recording_id],
    queryFn: () => api.get<LyricsResp>(`/api/lyrics/${current!.recording_id}`),
    enabled: !!current,
  });
  const lines = useMemo(() => (data?.synced ? parseLrc(data.synced) : []), [data?.synced]);
  const [t, setT] = useState(0);
  useEffect(() => {
    const a = audio.current;
    if (!a) return;
    const on = () => setT(a.currentTime);
    a.addEventListener("timeupdate", on);
    return () => a.removeEventListener("timeupdate", on);
  }, [audio, current]);
  let active = -1;
  for (let i = 0; i < lines.length; i++) if (lines[i].time <= t + 0.25) active = i;
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.querySelector(`[data-line="${active}"]`)?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [active]);

  return (
    <aside className="w-80 shrink-0 overflow-y-auto rounded-lg bg-gradient-to-b from-emerald-900/50 to-surface p-6 max-lg:hidden" ref={ref}>
      <h3 className="mb-4 text-sm font-bold uppercase tracking-wider text-muted-foreground">Lyrics</h3>
      {!current && <p className="text-sm text-muted-foreground">Nothing playing.</p>}
      {current && !data?.synced && !data?.plain && <p className="text-sm text-muted-foreground">No lyrics available{data?.status === "instrumental" ? " (instrumental)" : ""}.</p>}
      {lines.length > 0 ? (
        <div className="space-y-3 pb-40">
          {lines.map((l, i) => (
            <p
              key={i}
              data-line={i}
              onClick={() => audio.current && (audio.current.currentTime = l.time)}
              className={cn(
                "cursor-pointer text-xl font-bold leading-snug transition-colors",
                i === active ? "text-foreground" : i < active ? "text-foreground/40" : "text-foreground/25 hover:text-foreground/60",
              )}
            >
              {l.text || "♪"}
            </p>
          ))}
        </div>
      ) : (
        data?.plain && <pre className="whitespace-pre-wrap font-sans text-base font-semibold leading-relaxed text-foreground/80">{data.plain}</pre>
      )}
    </aside>
  );
}
