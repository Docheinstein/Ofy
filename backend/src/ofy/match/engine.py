"""Matching orchestration: Strategy A (official album) with Strategy B (per-song search) fallback."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from ofy.match import scoring
from ofy.match.scoring import MBAlbumQuery, MBTrackQuery, ScoredCandidate, YTCandidate
from ofy.match.ytm import YTMusicService, get_ytm
from ofy.mb import logic

log = logging.getLogger(__name__)

ALBUM_ACCEPT = 0.6  # minimum album score to use Strategy A mappings at all


@dataclass
class TrackMatch:
    track_id: str
    best: ScoredCandidate | None
    source: str | None  # album | song
    candidates: list[ScoredCandidate] = field(default_factory=list)

    @property
    def score(self) -> float:
        return self.best.score if self.best else 0.0


@dataclass
class AlbumMatch:
    album: dict[str, Any] | None
    tracks: dict[str, TrackMatch]


def album_query_from_release(release: dict[str, Any]) -> MBAlbumQuery:
    rows = logic.tracklist(release)
    rg = release.get("release-group") or {}
    tracks = [
        MBTrackQuery(
            track_id=r["track_id"], title=r["title"], artist=r["artist"], length_ms=r["length_ms"],
            disc=r["disc"], position=r["position"], index=i,
        )
        for i, r in enumerate(rows, start=1)
    ]
    return MBAlbumQuery(
        title=release.get("title", ""),
        artist=logic.artist_credit_string(release.get("artist-credit")),
        year=logic.year_of(rg.get("first-release-date") or release.get("date")),
        track_count=len(rows),
        primary_type=rg.get("primary-type"),
        tracks=tracks,
    )


async def find_album(q: MBAlbumQuery, ytm: YTMusicService, max_fetch: int = 3) -> tuple[dict[str, Any] | None, list[YTCandidate]]:
    results = await ytm.search_albums(f"{q.artist} {q.title}")
    pre: list[tuple[float, dict[str, Any]]] = []
    for r in results:
        if not r.get("browseId"):
            continue
        s = scoring.score_album(q, r.get("title", ""), [a.get("name", "") for a in r.get("artists") or []],
                                r.get("year"), r.get("type"))
        pre.append((s, r))
    pre.sort(key=lambda p: -p[0])
    best: tuple[float, dict[str, Any], list[YTCandidate]] | None = None
    for s, r in pre[:max_fetch]:
        if s < 0.45:
            break
        album = await ytm.get_album(r["browseId"])
        playlist = None
        if any(t.get("videoType") != scoring.ATV for t in album.get("tracks") or []) and album.get("audioPlaylistId"):
            try:
                playlist = await ytm.get_playlist_tracks(album["audioPlaylistId"])
            except Exception as e:
                log.info("audio playlist fetch failed: %s", e)
        tracks = scoring.album_tracks_from_ytm(album, r["browseId"], playlist)
        full = scoring.score_album(
            q, album.get("title", r.get("title", "")),
            [a.get("name", "") for a in album.get("artists") or r.get("artists") or []],
            album.get("year") or r.get("year"), album.get("type") or r.get("type"),
            album.get("trackCount") or len(tracks),
        )
        log.info("album candidate %r (%s): pre=%.2f full=%.2f", album.get("title"), r["browseId"], s, full)
        if best is None or full > best[0]:
            best = (full, {"browse_id": r["browseId"], "title": album.get("title"), "year": album.get("year"),
                           "track_count": album.get("trackCount"), "score": round(full, 4)}, tracks)
        if full >= 0.9:
            break
    if best is None:
        return None, []
    return best[1], best[2]


async def search_track(t: MBTrackQuery, album_title: str | None, ytm: YTMusicService) -> list[ScoredCandidate]:
    primary_artist = t.artist
    results = await ytm.search_songs(f"{primary_artist} {t.title}")
    cands = [c for r in results if (c := scoring.candidate_from_ytm(r, source="song"))]
    return scoring.rank_songs(t, album_title, cands)


async def match_release(release: dict[str, Any], threshold: float, ytm: YTMusicService | None = None,
                        only_track_ids: set[str] | None = None) -> AlbumMatch:
    ytm = ytm or get_ytm()
    q = album_query_from_release(release)
    album_info, yt_tracks = await find_album(q, ytm)
    mapping: dict[str, list[ScoredCandidate]] = {}
    if album_info and album_info["score"] >= ALBUM_ACCEPT and yt_tracks:
        mapping = scoring.map_album_tracks(q.tracks, yt_tracks, album_info["score"])
    out: dict[str, TrackMatch] = {}
    for t in q.tracks:
        if only_track_ids is not None and t.track_id not in only_track_ids:
            continue
        a_list = mapping.get(t.track_id, [])
        if a_list and a_list[0].score >= threshold:
            out[t.track_id] = TrackMatch(t.track_id, a_list[0], "album", a_list[:5])
            continue
        try:
            b_list = await search_track(t, q.title, ytm)
        except Exception as e:
            log.warning("song search failed for %s: %s", t.title, e)
            b_list = []
        merged = scoring.merge_candidates(a_list, b_list)
        best = merged[0] if merged else None
        out[t.track_id] = TrackMatch(t.track_id, best, best.candidate.source if best else None, merged)
    return AlbumMatch(album_info, out)


async def match_single(t: MBTrackQuery, album_title: str | None, ytm: YTMusicService | None = None) -> TrackMatch:
    """Quick Strategy-B-only match (used for streaming non-downloaded tracks)."""
    ytm = ytm or get_ytm()
    ranked = await search_track(t, album_title, ytm)
    best = ranked[0] if ranked else None
    return TrackMatch(t.track_id, best, "song" if best else None, ranked[:5])
