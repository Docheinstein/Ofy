"""Status aggregation (pure)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

TRACK_STATUSES = ("none", "queued", "downloading", "done", "failed", "needs_review")
LYRICS_STATUSES = ("none", "synced", "plain", "instrumental", "not_found")


def album_status(track_statuses: Iterable[str], total_tracks: int | None = None) -> str:
    """none | partial | complete.

    ``total_tracks`` is the number of tracks on the release; tracks never touched have no
    DB row, so they count as not downloaded.
    """
    statuses = list(track_statuses)
    total = max(total_tracks or 0, len(statuses))
    done = sum(1 for s in statuses if s == "done")
    if total == 0 or done == 0:
        return "none"
    if done >= total:
        return "complete"
    return "partial"


def album_summary(track_statuses: Iterable[str], total_tracks: int | None = None) -> dict:
    statuses = list(track_statuses)
    counts = Counter(statuses)
    total = max(total_tracks or 0, len(statuses))
    return {
        "status": album_status(statuses, total),
        "total": total,
        "done": counts.get("done", 0),
        "active": counts.get("queued", 0) + counts.get("downloading", 0),
        "failed": counts.get("failed", 0),
        "needs_review": counts.get("needs_review", 0),
    }
