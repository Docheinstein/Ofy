"""GET /api/stream/{recording_mbid}: local file (with HTTP Range) or proxied YouTube audio."""

from __future__ import annotations

import asyncio
import logging
import mimetypes
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from sqlmodel import select
from starlette.background import BackgroundTask

from offliner.cache import cache_delete, cache_get, cache_set
from offliner.db import Track, load_settings, session
from offliner.download.ytdlp import DownloadError, stream_info
from offliner.match.engine import match_release, match_single
from offliner.match.scoring import COMPOSITE_SEP, MBTrackQuery
from offliner.mb import logic
from offliner.mb.client import MusicBrainzError, get_mb

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["stream"])

MIME = {"mp3": "audio/mpeg", "m4a": "audio/mp4", "opus": "audio/ogg", "webm": "audio/webm", "mp4": "audio/mp4"}
_http: httpx.AsyncClient | None = None


def _client() -> httpx.AsyncClient:
    global _http
    if _http is None:
        _http = httpx.AsyncClient(timeout=httpx.Timeout(30, read=60), follow_redirects=True)
    return _http


def _local_file(recording_id: str) -> Path | None:
    with session() as s:
        tracks = s.exec(select(Track).where(Track.recording_id == recording_id, Track.status == "done")).all()
    for t in tracks:
        if t.file_path and Path(t.file_path).is_file():
            return Path(t.file_path)
    return None


async def resolve_video_id(recording_id: str, release_id: str | None) -> str:
    with session() as s:
        known = s.exec(select(Track).where(Track.recording_id == recording_id,
                                           Track.video_id.is_not(None))).first()  # type: ignore[union-attr]
    if known and known.video_id:
        return known.video_id.split(COMPOSITE_SEP)[0]
    key = f"stream:video:{recording_id}"
    cached = cache_get(key)
    if cached:
        return cached
    mb = get_mb()
    video_id: str | None = None
    if release_id:
        # Album context gives the most reliable match (and is cached for a later download).
        release = await mb.release(release_id)
        tid = next((r["track_id"] for r in logic.tracklist(release) if r["recording_id"] == recording_id), None)
        if tid:
            result = await match_release(release, load_settings().match_threshold, only_track_ids={tid})
            m = result.tracks.get(tid)
            if m and m.best:
                video_id = m.best.candidate.video_id
    if video_id is None:
        rec = await mb.recording(recording_id)
        best_rel = logic.pick_canonical_release(rec.get("releases") or [])
        q = MBTrackQuery(track_id=recording_id, title=rec.get("title", ""),
                         artist=logic.artist_credit_string(rec.get("artist-credit")), length_ms=rec.get("length"))
        m = await match_single(q, best_rel.get("title") if best_rel else None)
        if m.best:
            video_id = m.best.candidate.video_id
    if not video_id:
        raise HTTPException(404, "No YouTube Music match for this recording")
    video_id = video_id.split(COMPOSITE_SEP)[0]
    cache_set(key, video_id, 7 * 86400)
    return video_id


async def _stream_url(video_id: str) -> dict:
    key = f"stream:url:{video_id}"
    cached = cache_get(key)
    if cached:
        return cached
    settings = load_settings()
    try:
        info = await asyncio.to_thread(stream_info, video_id, cookies_path=settings.cookies_path or None)
    except DownloadError as e:
        raise HTTPException(502, f"yt-dlp: {e}") from e
    cache_set(key, info, 3600)  # googlevideo URLs expire after a few hours
    return info


@router.get("/stream/{recording_id}")
async def stream(recording_id: str, request: Request, release: str | None = None):
    local = _local_file(recording_id)
    if local:
        media = MIME.get(local.suffix.lstrip(".").lower()) or mimetypes.guess_type(local.name)[0] or "audio/mpeg"
        return FileResponse(local, media_type=media, headers={"Accept-Ranges": "bytes"})

    try:
        video_id = await resolve_video_id(recording_id, release)
    except MusicBrainzError as e:
        raise HTTPException(502, str(e)) from e
    info = await _stream_url(video_id)
    headers = dict(info.get("headers") or {})
    rng = request.headers.get("range")
    if rng:
        headers["Range"] = rng
    client = _client()
    upstream_req = client.build_request("GET", info["url"], headers=headers)
    upstream = await client.send(upstream_req, stream=True)
    if upstream.status_code in (403, 410):
        # Expired/forbidden URL: drop the cache and retry once with a fresh extraction.
        await upstream.aclose()
        cache_delete(f"stream:url:{video_id}")
        info = await _stream_url(video_id)
        upstream = await client.send(client.build_request("GET", info["url"], headers={
            **(info.get("headers") or {}), **({"Range": rng} if rng else {})}), stream=True)
    if upstream.status_code >= 400:
        await upstream.aclose()
        raise HTTPException(502, f"upstream returned {upstream.status_code}")
    out_headers = {"Accept-Ranges": "bytes", "Cache-Control": "no-store"}
    for h in ("content-length", "content-range"):
        if h in upstream.headers:
            out_headers[h] = upstream.headers[h]
    media = MIME.get((info.get("ext") or "").lower(), "audio/mp4")
    return StreamingResponse(
        upstream.aiter_raw(), status_code=upstream.status_code, media_type=media, headers=out_headers,
        background=BackgroundTask(upstream.aclose),
    )
