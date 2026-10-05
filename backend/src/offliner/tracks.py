"""Track/album persistence helpers and live event publishing."""

from __future__ import annotations

import json
import time
from typing import Any

from sqlmodel import col, select

from offliner.db import Album, Track, session
from offliner.events import hub
from offliner.mb import logic


def event_for(t: Track) -> dict[str, Any]:
    return {
        "type": "track",
        "track_id": t.track_id,
        "release_id": t.release_id,
        "recording_id": t.recording_id,
        "status": t.status,
        "stage": t.stage,
        "progress": round(t.progress, 3),
        "lyrics_status": t.lyrics_status,
        "error": t.error,
    }


def get_track(track_id: str) -> Track | None:
    with session() as s:
        return s.get(Track, track_id)


def update_track(track_id: str, *, publish: bool = True, **fields: Any) -> Track:
    with session() as s:
        t = s.get(Track, track_id)
        if t is None:
            raise KeyError(track_id)
        for k, v in fields.items():
            setattr(t, k, v)
        t.updated_at = time.time()
        s.add(t)
        s.commit()
        s.refresh(t)
    if publish:
        hub.publish(event_for(t))
    return t


def publish_progress(t: Track, progress: float, stage: str) -> None:
    """Progress tick without a DB write (DB is updated on stage changes)."""
    ev = event_for(t)
    ev.update(progress=round(progress, 3), stage=stage, status="downloading")
    hub.publish(ev)


def ensure_release_rows(release: dict[str, Any]) -> list[Track]:
    """Create Album + Track rows for a release (idempotent); refresh their metadata."""
    rows = logic.tracklist(release)
    rg = release.get("release-group") or {}
    with session() as s:
        album = s.get(Album, release["id"]) or Album(
            release_id=release["id"], release_group_id=rg.get("id", ""), title="", artist=""
        )
        album.release_group_id = rg.get("id", album.release_group_id)
        album.title = release.get("title", "")
        album.artist = logic.artist_credit_string(release.get("artist-credit"))
        album.artist_id = (logic.artist_credit_ids(release.get("artist-credit")) or [None])[0]
        album.year = logic.year_of(rg.get("first-release-date") or release.get("date"))
        album.track_count = len(rows)
        album.updated_at = time.time()
        s.add(album)
        out = []
        for r in rows:
            t = s.get(Track, r["track_id"]) or Track(
                track_id=r["track_id"], recording_id=r["recording_id"], release_id=release["id"],
                release_group_id=rg.get("id", ""),
            )
            t.recording_id = r["recording_id"]
            t.disc = r["disc"]
            t.position = r["position"]
            t.title = r["title"]
            t.artist = r["artist"]
            t.length_ms = r["length_ms"]
            s.add(t)
            out.append(t)
        s.commit()
        for t in out:
            s.refresh(t)
    return out


def tracks_for_release(release_id: str) -> list[Track]:
    with session() as s:
        return list(s.exec(select(Track).where(Track.release_id == release_id)
                           .order_by(col(Track.disc), col(Track.position))).all())


def save_candidates(track_id: str, candidates: list[dict[str, Any]]) -> None:
    with session() as s:
        t = s.get(Track, track_id)
        if t:
            t.candidates = json.dumps(candidates)
            s.add(t)
            s.commit()
