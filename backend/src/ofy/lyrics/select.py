"""LRCLIB result selection and .lrc formatting (pure)."""

from __future__ import annotations

import re
from typing import Any

from ofy.match.scoring import artist_similarity, text_similarity

DURATION_TOLERANCE = 2.0
MATCH_THRESHOLD = 0.8

_TIMESTAMP = re.compile(r"\[\d{1,3}:\d{2}(?:[.:]\d{1,3})?\]")
_HEADER = re.compile(r"^\[(ar|al|ti|au|length|by|offset|re|ve|#):.*\]\s*$", re.I)


def result_score(r: dict[str, Any], title: str, artist: str) -> float:
    t = text_similarity(title, r.get("trackName") or r.get("name"))
    a = artist_similarity(artist, [r.get("artistName") or ""])
    return 0.6 * t + 0.4 * a


def select_search_result(results: list[dict[str, Any]], title: str, artist: str, duration_s: float | None, *,
                         tolerance: float = DURATION_TOLERANCE, threshold: float = MATCH_THRESHOLD,
                         prefer_synced: bool = True) -> dict[str, Any] | None:
    """Best /api/search result within ±tolerance seconds whose title/artist match above threshold."""
    ok: list[tuple[float, dict[str, Any]]] = []
    for r in results:
        if duration_s is not None:
            d = r.get("duration")
            if d is None or abs(float(d) - duration_s) > tolerance:
                continue
        t = text_similarity(title, r.get("trackName") or r.get("name"))
        a = artist_similarity(artist, [r.get("artistName") or ""])
        if t < threshold or a < threshold:
            continue
        score = 0.6 * t + 0.4 * a
        has_lyrics = bool(r.get("syncedLyrics") or r.get("plainLyrics") or r.get("instrumental"))
        if not has_lyrics:
            continue
        if prefer_synced and r.get("syncedLyrics"):
            score += 0.05
        ok.append((score, r))
    if not ok:
        return None
    ok.sort(key=lambda p: -p[0])
    return ok[0][1]


def strip_timestamps(synced: str) -> str:
    lines = []
    for line in synced.splitlines():
        if _HEADER.match(line.strip()):
            continue
        lines.append(_TIMESTAMP.sub("", line).strip())
    text = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", text)


def format_length(seconds: float | None) -> str:
    if seconds is None:
        return "00:00"
    s = int(round(seconds))
    return f"{s // 60:02d}:{s % 60:02d}"


def format_lrc(synced: str, *, artist: str, album: str, title: str, length_s: float | None) -> str:
    """LRC file with [ar:], [al:], [ti:], [length:] headers; existing headers in ``synced`` are replaced."""
    body = [line.rstrip() for line in synced.strip().splitlines() if not _HEADER.match(line.strip())]
    header = [
        f"[ar:{artist}]",
        f"[al:{album}]",
        f"[ti:{title}]",
        f"[length:{format_length(length_s)}]",
    ]
    return "\n".join(header + body) + "\n"


def classify(r: dict[str, Any] | None, prefer_synced: bool = True) -> str:
    """synced | plain | instrumental | not_found for an LRCLIB record."""
    if not r:
        return "not_found"
    if r.get("instrumental"):
        return "instrumental"
    if r.get("syncedLyrics") and prefer_synced:
        return "synced"
    if r.get("plainLyrics") or r.get("syncedLyrics"):
        return "plain"
    return "not_found"
