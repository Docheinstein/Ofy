import { useEffect, useSyncExternalStore } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { TrackEvent, TrackState } from "./api";

type Live = Partial<TrackState> & { status: TrackState["status"] };

const state = new Map<string, Live>();
const listeners = new Set<() => void>();
let version = 0;

function emit() {
  version++;
  listeners.forEach((l) => l());
}

export function setLive(trackId: string, v: Live) {
  state.set(trackId, v);
  emit();
}

function subscribe(l: () => void) {
  listeners.add(l);
  return () => listeners.delete(l);
}

/** Live (WebSocket-pushed) state for a track, overriding server-fetched data while it's newer. */
export function useLiveTrack(trackId: string): Live | undefined {
  useSyncExternalStore(subscribe, () => version);
  return state.get(trackId);
}

export function useLiveVersion() {
  return useSyncExternalStore(subscribe, () => version);
}

/** Connects to /api/ws, keeps the live store up to date and invalidates affected queries. */
export function useLiveUpdates() {
  const qc = useQueryClient();
  useEffect(() => {
    let ws: WebSocket | null = null;
    let closed = false;
    let retry = 1000;
    let timer: number | undefined;
    const pending = new Set<string>();
    const flush = () => {
      timer = undefined;
      const releases = [...pending];
      pending.clear();
      releases.forEach((r) => qc.invalidateQueries({ queryKey: ["release", r] }));
      qc.invalidateQueries({ queryKey: ["library"] });
      qc.invalidateQueries({ queryKey: ["downloads"] });
      qc.invalidateQueries({ queryKey: ["track"] });
      qc.invalidateQueries({ queryKey: ["artist"] });
      qc.invalidateQueries({ queryKey: ["search"] });
    };
    const connect = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${location.host}/api/ws`);
      ws.onopen = () => (retry = 1000);
      ws.onmessage = (m) => {
        const ev = JSON.parse(m.data) as TrackEvent | { type: string; release_id?: string };
        if (ev.type === "track") {
          const t = ev as TrackEvent;
          setLive(t.track_id, {
            status: t.status,
            stage: t.stage,
            progress: t.progress,
            lyrics_status: t.lyrics_status,
            error: t.error,
          });
          // Progress ticks don't need refetches; status transitions do.
          if (t.stage === "downloading" && t.status === "downloading" && t.progress > 0 && t.progress < 1) return;
          pending.add(t.release_id);
        } else if (ev.type === "library") {
          state.clear();
          emit();
        }
        if (!timer) timer = window.setTimeout(flush, 400);
      };
      ws.onclose = () => {
        if (closed) return;
        setTimeout(connect, retry);
        retry = Math.min(retry * 2, 15000);
      };
    };
    connect();
    return () => {
      closed = true;
      ws?.close();
    };
  }, [qc]);
}
