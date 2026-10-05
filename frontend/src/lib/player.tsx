import { createContext, useCallback, useContext, useMemo, useRef, useState } from "react";

export interface PlayItem {
  recording_id: string;
  track_id?: string;
  release_id?: string;
  title: string;
  artist: string;
  cover?: string;
  length_ms?: number | null;
}

interface PlayerCtx {
  queue: PlayItem[];
  index: number;
  current: PlayItem | null;
  playing: boolean;
  audio: React.RefObject<HTMLAudioElement>;
  playList: (items: PlayItem[], start?: number) => void;
  toggle: () => void;
  next: () => void;
  prev: () => void;
  setPlaying: (p: boolean) => void;
}

const Ctx = createContext<PlayerCtx | null>(null);

export function PlayerProvider({ children }: { children: React.ReactNode }) {
  const [queue, setQueue] = useState<PlayItem[]>([]);
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const audio = useRef<HTMLAudioElement>(null);

  const playList = useCallback((items: PlayItem[], start = 0) => {
    setQueue(items);
    setIndex(start);
    setPlaying(true);
  }, []);
  const toggle = useCallback(() => {
    const a = audio.current;
    if (!a) return;
    if (a.paused) void a.play();
    else a.pause();
  }, []);
  const next = useCallback(() => setIndex((i) => (i + 1 < queue.length ? i + 1 : i)), [queue.length]);
  const prev = useCallback(() => {
    const a = audio.current;
    if (a && a.currentTime > 3) {
      a.currentTime = 0;
      return;
    }
    setIndex((i) => Math.max(0, i - 1));
  }, []);

  const value = useMemo(
    () => ({ queue, index, current: queue[index] ?? null, playing, audio, playList, toggle, next, prev, setPlaying }),
    [queue, index, playing, playList, toggle, next, prev],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function usePlayer() {
  const c = useContext(Ctx);
  if (!c) throw new Error("usePlayer outside provider");
  return c;
}
