"""Downloading pasted YouTube links: one video, or every video of a playlist.

YouTube only provides the audio. Each video is matched to a MusicBrainz recording, from the title,
artist and length YouTube Music reports, and downloaded as that recording's track on one of its
releases, so it is tagged, named and shown in the library like anything picked from the catalogue.
A video without a confident match waits for the user to choose the recording.
"""

from __future__ import annotations

import json
import logging
import math
import re
import time
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse

from sqlmodel import col, select

from ofy.db import Album, Job, Track, YTImport, session
from ofy.jobs import PermanentError, queue
from ofy.match import scoring
from ofy.match.ytm import get_ytm
from ofy.mb import logic
from ofy.mb.client import get_mb
from ofy.tagging.model import VARIOUS_ARTISTS_ID
from ofy.tracks import ensure_release_rows, update_track

log = logging.getLogger(__name__)

ACCEPT = 0.8  # a recording scoring this much is downloaded without asking
JOB_KIND = "yt_resolve"
JOB_PREFIX = "yt:"  # the resolve job carries its import as track_id "yt:<import id>"

_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_BRACKETS = re.compile(r"\s*[\(\[\{][^\)\]\}]*[\)\]\}]")
_CHANNEL_SUFFIX = re.compile(r"\s*(?:-\s*topic|vevo|official)$", re.I)


# --- links ---------------------------------------------------------------------------------------

@dataclass
class Link:
    kind: str  # video | playlist | album
    id: str


def parse_link(url: str) -> Link:
    """A video (watch?v=, youtu.be/, /shorts/, /embed/, /live/ or a bare id), a playlist (?list=)
    or a YouTube Music album (/browse/MPREb_…). A watch link opened from a playlist is the video alone."""
    url = url.strip()
    if _VIDEO_ID.match(url):
        return Link("video", url)
    u = urlparse(url if "://" in url else f"https://{url}")
    host = (u.hostname or "").lower().removeprefix("www.").removeprefix("m.")
    q = parse_qs(u.query)
    parts = [p for p in u.path.split("/") if p]
    if host == "youtu.be" and parts:
        vid = parts[0]
    elif host.endswith(("youtube.com", "youtube-nocookie.com")):
        if q.get("v"):
            vid = q["v"][0]
        elif len(parts) >= 2 and parts[0] in ("shorts", "embed", "live", "v"):
            vid = parts[1]
        elif q.get("list"):
            return Link("playlist", q["list"][0])
        elif len(parts) == 2 and parts[0] == "browse" and parts[1].startswith("MPREb_"):
            return Link("album", parts[1])
        elif len(parts) == 2 and parts[0] == "browse" and parts[1].startswith("VL"):
            return Link("playlist", parts[1][2:])
        else:
            raise ValueError("Not a link to a YouTube video or playlist")
    else:
        raise ValueError("Not a YouTube link")
    if not _VIDEO_ID.match(vid):
        raise ValueError("Not a valid YouTube video link")
    return Link("video", vid)


def _seconds(length: str | None) -> int | None:
    try:
        n = 0
        for part in (length or "").split(":"):
            n = n * 60 + int(part)
        return n or None
    except ValueError:
        return None


def yt_metadata(t: dict[str, Any]) -> dict[str, Any]:
    """YTImport fields from a ytmusicapi track (playlist entry or watch-playlist item)."""
    album = t.get("album")
    return {
        "title": t.get("title") or "",
        "artists": json.dumps([a["name"] for a in t.get("artists") or [] if a.get("name")]),
        "album": album.get("name") if isinstance(album, dict) else album,
        "duration": t.get("duration_seconds") or _seconds(t.get("length") or t.get("duration")),
        "video_type": t.get("videoType"),
    }


# --- starting an import --------------------------------------------------------------------------

async def start_import(url: str) -> dict[str, Any]:
    link = parse_link(url)
    ytm = get_ytm()
    title = ""
    if link.kind == "video":
        batch = link.id
        entries: list[dict[str, Any]] = [{"videoId": link.id}]  # the job looks the video up
    else:
        playlist_id = link.id
        if link.kind == "album":
            album = await ytm.get_album(link.id)
            playlist_id = album.get("audioPlaylistId") or ""
            title = album.get("title") or ""
            if not playlist_id:
                raise ValueError("This album has no playable tracks")
        try:
            playlist = await ytm.get_full_playlist(playlist_id)
        except RuntimeError as e:
            raise ValueError("Playlist not found: it may be private") from e
        title = title or playlist.get("title") or ""
        batch = playlist_id
        entries = [t for t in playlist.get("tracks") or [] if t.get("videoId") and t.get("isAvailable") is not False]
        if not entries:
            raise ValueError("The playlist has no playable videos")

    queued: list[int] = []
    with session() as s:
        existing = {i.video_id: i for i in s.exec(select(YTImport).where(YTImport.batch == batch)).all()}
        for pos, e in enumerate(entries):
            imp = existing.get(e["videoId"])
            if imp is not None:
                if imp.status != "failed":
                    continue  # pasted again: keep what was already done or decided
                imp.status, imp.error, imp.updated_at = "resolving", None, time.time()
            else:
                imp = YTImport(video_id=e["videoId"], batch=batch, batch_title=title, position=pos,
                               **(yt_metadata(e) if e.get("title") else {}))
            s.add(imp)
            s.commit()
            s.refresh(imp)
            queued.append(imp.id)  # type: ignore[arg-type]
    for i in queued:
        queue.enqueue(JOB_KIND, track_id=f"{JOB_PREFIX}{i}")
    return {"kind": "video" if link.kind == "video" else "playlist", "batch": batch, "title": title,
            "queued": len(queued), "total": len(entries)}


# --- matching against MusicBrainz ----------------------------------------------------------------

@dataclass
class Candidate:
    recording_id: str
    title: str
    artist: str
    length_ms: int | None
    disambiguation: str | None
    release_id: str
    release_title: str
    release_group_id: str | None
    date: str | None
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "score": round(min(1.0, self.score), 4)}


def clean_title(title: str) -> str:
    """Video title without "(Official Video)", "[HD]", "| Lyrics"… (used to search, not to score)."""
    title = _BRACKETS.sub("", title).split("|")[0]
    return re.sub(r"\s+", " ", title).strip(" -–—") or title.strip()


def query_variants(title: str, artists: list[str], video_type: str | None) -> list[tuple[str, tuple[str, ...]]]:
    """(title, artists) readings of a video, most likely first. Official audio and videos have proper
    music metadata; other uploads usually say "Artist - Title" and come from a channel named anything."""
    names = tuple(n for a in artists if (n := _CHANNEL_SUFFIX.sub("", a).strip()))
    out: list[tuple[str, tuple[str, ...]]] = []
    split = re.split(r"\s[-–—]\s", title, maxsplit=1) if video_type != scoring.ATV else []
    if len(split) == 2:
        left, right = (p.strip() for p in split)
        out.append((clean_title(right), (left,)))
    out.append((clean_title(title), names))
    if len(split) == 2:
        out.append((clean_title(left), (clean_title(right),)))  # "Title - Artist"
    return [(t, a) for t, a in dict.fromkeys(out) if t and a]


def _phrase(s: str) -> str:
    return '"' + s.replace("\\", " ").replace('"', " ") + '"'


def various_artists(release: dict[str, Any]) -> bool:
    return any((c.get("artist") or {}).get("id") == VARIOUS_ARTISTS_ID or c.get("name") == "Various Artists"
               for c in release.get("artist-credit") or [])


def release_quality(release: dict[str, Any], yt_title: str) -> float:
    """How much a release vouches for its recording being *the* song: the artist's own official
    studio album most; a live album (unless the video is live too) or a various-artists
    compilation, which often carries its own copy of a hit, least."""
    rg = release.get("release-group") or {}
    secondary = set(rg.get("secondary-types") or [])
    if release.get("status") != "Official" or various_artists(release):
        return 0.5
    if "Live" in secondary and "live" not in scoring.variant_terms(yt_title):
        return 0.4
    if not secondary:
        return 1.0 if rg.get("primary-type") == "Album" else 0.9
    return 0.8 if secondary == {"Compilation"} else 0.7


def pick_release(releases: list[dict[str, Any]], yt_album: str | None, in_library: set[str]) -> dict[str, Any] | None:
    """The release to file the song under: one already in the library, else the album YouTube names,
    else the canonical official studio album, single or EP; the artist's own releases before
    various-artists compilations."""
    pool = [r for r in releases if r.get("status") == "Official"] or releases
    pool = [r for r in pool if not various_artists(r)] or pool

    def studio(r: dict[str, Any]) -> bool:
        rg = r.get("release-group") or {}
        return rg.get("primary-type") == "Album" and not rg.get("secondary-types")

    for keep in (
        lambda r: r["id"] in in_library,
        lambda r: bool(yt_album) and scoring.text_similarity(r.get("title"), yt_album) >= 0.85,
        studio,
        lambda r: not (r.get("release-group") or {}).get("secondary-types"),
    ):
        sub = [r for r in pool if keep(r)]
        if sub:
            return logic.pick_canonical_release(sub)
    return logic.pick_canonical_release(pool)


def score_recording(hit: dict[str, Any], title: str, artists: tuple[str, ...], imp: YTImport,
                    in_library: set[str]) -> Candidate | None:
    """How likely the recording is this video. Not capped at 1, so near-equal ones still rank
    (the original studio recording over a reissue's copy of it)."""
    releases = hit.get("releases") or []
    release = pick_release(releases, imp.album, in_library)
    if release is None:
        return None
    credit = logic.artist_credit_string(hit.get("artist-credit"))
    title_s = scoring.text_similarity(hit.get("title"), title)
    artist_s = scoring.artist_similarity(credit, list(artists))
    base = 0.6 * title_s + 0.4 * artist_s
    # A different length is a different version (radio edit, live…). Official audio has the
    # record's length; a music video often has an intro or a cut of its own, so trust it less.
    if hit.get("length") and imp.duration:
        weight = 0.25 if imp.video_type == scoring.ATV else 0.15
        base *= 1 - weight + weight * scoring.duration_similarity(hit["length"], imp.duration)
    else:
        base *= 0.9
    if artist_s < scoring.ARTIST_MIN:
        base *= 0.5
    # a live/remix/… recording for a video that doesn't say so, or the other way round
    base *= scoring.variant_penalty(f"{hit.get('title', '')} {hit.get('disambiguation') or ''}", imp.title)
    quality = max(release_quality(r, imp.title) for r in releases)
    official = sum(r.get("status") == "Official" for r in releases)
    # The song as most people know it is on many releases, the artist's albums among them; a
    # compilation's or a remaster's own copy of it is on one or two.
    score = base * (0.6 + 0.4 * quality) + 0.08 * min(1.0, math.log1p(official) / math.log1p(50))
    if any(r["id"] in in_library for r in releases):
        score += 0.02  # the same song already downloaded from one of its releases
    return Candidate(
        recording_id=hit["id"], title=hit.get("title", ""), artist=credit, length_ms=hit.get("length"),
        disambiguation=hit.get("disambiguation") or None, release_id=release["id"],
        release_title=release.get("title", ""), release_group_id=(release.get("release-group") or {}).get("id"),
        date=release.get("date") or None, score=score,
    )


async def find_recordings(imp: YTImport) -> list[Candidate]:
    """MusicBrainz recordings that could be this video, best first."""
    mb = get_mb()
    with session() as s:
        in_library = set(s.exec(select(Album.release_id)).all())
    artists = json.loads(imp.artists or "[]")
    variants = query_variants(imp.title, artists, imp.video_type)
    best: dict[str, Candidate] = {}

    def done() -> bool:
        return bool(best) and max(c.score for c in best.values()) >= ACCEPT

    # A popular song has more recordings than one page of results: when the first page has no
    # good one, ask again for those as long as the video. Bootlegs and promos only if nothing
    # official comes up at all.
    narrow = [""]
    if imp.duration:
        narrow.append(f" AND dur:[{(imp.duration - 6) * 1000} TO {(imp.duration + 6) * 1000}]")
    for status in (" AND status:official", ""):
        for title, artists in variants:
            for extra in narrow:
                query = f"recording:{_phrase(title)} AND ({' OR '.join(f'artist:{_phrase(a)}' for a in artists)}){status}{extra}"
                data = await mb.search("recording", query, limit=50)
                for hit in data.get("recordings") or []:
                    c = score_recording(hit, title, artists, imp, in_library)
                    if c and (c.recording_id not in best or c.score > best[c.recording_id].score):
                        best[c.recording_id] = c
                if done():
                    return _ranked(best)
        if best:
            break
    return _ranked(best)


def _ranked(best: dict[str, Candidate]) -> list[Candidate]:
    return sorted(best.values(), key=lambda c: -c.score)


# --- the job --------------------------------------------------------------------------------------

def get_import(import_id: int) -> YTImport | None:
    with session() as s:
        return s.get(YTImport, import_id)


def update_import(import_id: int, **fields: Any) -> YTImport:
    with session() as s:
        imp = s.get(YTImport, import_id)
        if imp is None:
            raise KeyError(import_id)
        for k, v in fields.items():
            setattr(imp, k, v)
        imp.updated_at = time.time()
        s.add(imp)
        s.commit()
        s.refresh(imp)
        return imp


def import_id_of(job: Job) -> int:
    return int((job.track_id or "").removeprefix(JOB_PREFIX))


async def handle_resolve(job: Job) -> None:
    import_id = import_id_of(job)
    imp = get_import(import_id)
    if imp is None or imp.status != "resolving":
        return
    if not imp.title:
        info = await get_ytm().get_track(imp.video_id)
        if info is None:
            raise PermanentError("Video not found on YouTube Music")
        imp = update_import(import_id, **yt_metadata(info))
    cands = await find_recordings(imp)
    if cands and cands[0].score >= ACCEPT:
        await use_recording(import_id, cands[0].recording_id, cands[0].release_id, min(1.0, cands[0].score))
        return
    update_import(
        import_id, status="needs_review", candidates=json.dumps([c.to_dict() for c in cands[:8]]),
        match_score=min(1.0, cands[0].score) if cands else None,
        error=None if cands else "Nothing like it on MusicBrainz",
    )


async def on_resolve_failed(job: Job, final_error: str) -> None:
    if job.status == "failed" and get_import(import_id_of(job)):
        update_import(import_id_of(job), status="failed", error=(final_error or job.error or "failed")[:500])


async def use_recording(import_id: int, recording_id: str, release_id: str, score: float | None) -> YTImport:
    """Download the video as this recording's track on that release (unless it is already there)."""
    imp = get_import(import_id)
    if imp is None:
        raise KeyError(import_id)
    release = await get_mb().release(release_id)
    tracks = ensure_release_rows(release)
    t = next((t for t in tracks if t.recording_id == recording_id), None)
    if t is None:
        raise PermanentError("That recording is not on the release")
    common = {"track_id": t.track_id, "release_id": release_id, "match_score": score, "error": None}
    if t.status == "done":
        return update_import(import_id, status="in_library", **common)
    if t.status not in ("queued", "downloading"):
        queue.cancel_for_track(t.track_id)
        # The pasted video is the audio source, as if picked by hand among the YouTube candidates.
        update_track(t.track_id, video_id=imp.video_id, match_source="manual", match_score=1.0,
                     status="queued", stage=None, progress=0, error=None)
        queue.enqueue("download", track_id=t.track_id, release_id=release_id)
    return update_import(import_id, status="matched", **common)


async def choose_recording(import_id: int, recording_id: str, release_id: str | None) -> YTImport:
    """The user's pick for a video without a confident match."""
    if release_id is None:
        rec = await get_mb().recording(recording_id)
        with session() as s:
            in_library = set(s.exec(select(Album.release_id)).all())
        imp = get_import(import_id)
        release = pick_release(rec.get("releases") or [], imp.album if imp else None, in_library)
        if release is None:
            raise PermanentError("The recording is not on any release")
        release_id = release["id"]
    return await use_recording(import_id, recording_id, release_id, None)


def retry_import(import_id: int) -> None:
    update_import(import_id, status="resolving", error=None, candidates="[]")
    queue.enqueue(JOB_KIND, track_id=f"{JOB_PREFIX}{import_id}")


# --- listing --------------------------------------------------------------------------------------

def list_imports(limit: int = 500) -> list[dict[str, Any]]:
    with session() as s:
        rows = list(s.exec(select(YTImport).order_by(col(YTImport.created_at).desc(), col(YTImport.position))
                           .limit(limit)).all())
        ids = {r.track_id for r in rows if r.track_id}
        tracks = {t.track_id: t for t in s.exec(select(Track).where(col(Track.track_id).in_(ids))).all()}
        albums = {a.release_id: a for a in s.exec(select(Album)).all()}
    out = []
    for r in rows:
        t = tracks.get(r.track_id or "")
        a = albums.get(r.release_id or "")
        out.append({
            **r.model_dump(exclude={"artists", "candidates"}),
            "artists": json.loads(r.artists or "[]"),
            "candidates": json.loads(r.candidates or "[]"),
            "track": {
                "title": t.title, "artist": t.artist, "recording_id": t.recording_id, "status": t.status,
                "stage": t.stage, "progress": t.progress, "error": t.error, "album": a.title if a else None,
                "release_group_id": t.release_group_id,
            } if t else None,
        })
    return out


def clear_finished() -> int:
    """Forget imports that are in the library now (downloaded, or already there)."""
    with session() as s:
        rows = list(s.exec(select(YTImport).where(col(YTImport.status).in_(["matched", "in_library"]))).all())
        done = {t.track_id for t in s.exec(select(Track).where(Track.status == "done")).all()}
        gone = [r for r in rows if r.status == "in_library" or r.track_id in done]
        for r in gone:
            s.delete(r)
        s.commit()
        return len(gone)
