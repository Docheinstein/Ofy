"""Lyrics step: fetch from LRCLIB, decide what to save, write sidecar files. Best-effort."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

import httpx

from offliner.config import Settings
from offliner.lyrics import select
from offliner.lyrics.client import LrclibClient, LrclibError
from offliner.tagging.model import TagModel

log = logging.getLogger(__name__)


@dataclass
class LyricsOutcome:
    status: str  # synced | plain | instrumental | not_found | error
    synced: str | None = None
    plain: str | None = None
    error: str | None = None

    @property
    def embed_text(self) -> str | None:
        """Plain (unsynchronized) lyrics for embedding in tags."""
        if self.status in ("synced", "plain"):
            if self.plain:
                return self.plain.strip()
            if self.synced:
                return select.strip_timestamps(self.synced)
        return None


def outcome_from_record(r: dict | None, prefer_synced: bool) -> LyricsOutcome:
    status = select.classify(r, prefer_synced)
    if status in ("not_found", "instrumental") or r is None:
        return LyricsOutcome(status)
    return LyricsOutcome(status, synced=r.get("syncedLyrics") or None, plain=r.get("plainLyrics") or None)


async def fetch_for_model(model: TagModel, settings: Settings, *,
                          transport: httpx.AsyncBaseTransport | None = None) -> LyricsOutcome:
    """Never raises: failures are reported as status 'error'."""
    duration = round(model.length_ms / 1000) if model.length_ms else None
    artist = model.artist or model.albumartist
    try:
        async with LrclibClient(settings.lrclib_url, transport=transport) as c:
            rec = await c.get(artist=artist, title=model.title, album=model.album, duration=duration)
            if rec is None or not (rec.get("syncedLyrics") or rec.get("plainLyrics") or rec.get("instrumental")):
                results = await c.search(artist=artist, title=model.title, album=model.album)
                rec = select.select_search_result(
                    results, model.title, artist, duration, prefer_synced=settings.lyrics_prefer_synced
                ) or rec
        return outcome_from_record(rec, settings.lyrics_prefer_synced)
    except (LrclibError, httpx.HTTPError, ValueError) as e:
        log.warning("lyrics lookup failed for %s – %s: %s", artist, model.title, e)
        return LyricsOutcome("error", error=str(e))
    except Exception as e:  # pragma: no cover - lyrics must never break a download
        log.exception("unexpected lyrics failure")
        return LyricsOutcome("error", error=str(e))


def sidecar_status(audio: Path) -> str:
    if audio.with_suffix(".lrc").is_file():
        return "synced"
    if audio.with_suffix(".txt").is_file():
        return "plain"
    return "none"


def _write_text(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.part")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def write_sidecar(audio: Path, outcome: LyricsOutcome, model: TagModel, settings: Settings) -> tuple[str, Path | None]:
    """Write "<basename>.lrc" or "<basename>.txt" next to the audio file. Returns (status, path)."""
    lrc, txt = audio.with_suffix(".lrc"), audio.with_suffix(".txt")
    try:
        if outcome.status == "error":
            st = sidecar_status(audio)
            return st, (lrc if st == "synced" else txt if st == "plain" else None)
        if outcome.status == "synced" and outcome.synced:
            length = model.length_ms / 1000 if model.length_ms else None
            _write_text(lrc, select.format_lrc(outcome.synced, artist=model.artist, album=model.album,
                                               title=model.title, length_s=length))
            txt.unlink(missing_ok=True)
            return "synced", lrc
        if outcome.status in ("plain", "synced"):
            text = outcome.embed_text
            if text:
                _write_text(txt, text + "\n")
                lrc.unlink(missing_ok=True)
                return "plain", txt
            return "not_found", None
        if outcome.status == "instrumental":
            lrc.unlink(missing_ok=True)
            txt.unlink(missing_ok=True)
            return "instrumental", None
        return "not_found", None
    except OSError as e:
        log.warning("writing lyrics sidecar failed: %s", e)
        return sidecar_status(audio), None
