"""Pure transformations of MusicBrainz JSON (no I/O)."""

from __future__ import annotations

from typing import Any

DISCOGRAPHY_ORDER = ["Album", "Single/EP", "Compilation", "Live", "Other"]

# Higher = better. "Digital Media" and CD are preferred per spec; vinyl/cassette etc. lower.
FORMAT_RANK = {
    "Digital Media": 3,
    "CD": 3,
    "Enhanced CD": 2,
    "HDCD": 2,
    "SACD": 1,
    "Hybrid SACD": 1,
    "Blu-spec CD": 2,
    "SHM-CD": 2,
}
COUNTRY_RANK = {"XW": 5, "XE": 4, "GB": 3, "US": 3}
STATUS_RANK = {"Official": 3, "Promotion": 1, "Bootleg": 0, "Pseudo-Release": -1}


def artist_credit_string(credits: list[dict[str, Any]] | None) -> str:
    if not credits:
        return ""
    return "".join(f"{c.get('name') or c.get('artist', {}).get('name', '')}{c.get('joinphrase', '')}"
                   for c in credits).strip()


def artist_credit_names(credits: list[dict[str, Any]] | None) -> list[str]:
    return [c.get("artist", {}).get("name") or c.get("name", "") for c in credits or []]


def artist_credit_ids(credits: list[dict[str, Any]] | None) -> list[str]:
    return [c["artist"]["id"] for c in credits or [] if c.get("artist", {}).get("id")]


def artist_credit_sort(credits: list[dict[str, Any]] | None) -> str:
    """Sort name of the credit, keeping join phrases (Picard behaviour)."""
    if not credits:
        return ""
    return "".join(
        f"{c.get('artist', {}).get('sort-name') or c.get('name', '')}{c.get('joinphrase', '')}" for c in credits
    ).strip()


def year_of(date: str | None) -> str | None:
    if date and len(date) >= 4 and date[:4].isdigit():
        return date[:4]
    return None


def discography_bucket(rg: dict[str, Any]) -> str:
    primary = rg.get("primary-type") or ""
    secondary = set(rg.get("secondary-types") or [])
    if "Live" in secondary:
        return "Live"
    if "Compilation" in secondary:
        return "Compilation"
    if secondary & {"Soundtrack", "Remix", "DJ-mix", "Mixtape/Street", "Demo", "Interview", "Spokenword",
                    "Audiobook", "Audio drama", "Field recording"}:
        return "Other"
    if primary == "Album":
        return "Album"
    if primary in ("Single", "EP"):
        return "Single/EP"
    return "Other"


def summarize_release_group(rg: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": rg["id"],
        "title": rg.get("title", ""),
        "primary_type": rg.get("primary-type"),
        "secondary_types": rg.get("secondary-types") or [],
        "first_release_date": rg.get("first-release-date") or None,
        "year": year_of(rg.get("first-release-date")),
        "artist": artist_credit_string(rg.get("artist-credit")),
        "artist_id": (artist_credit_ids(rg.get("artist-credit")) or [None])[0],
    }


def group_discography(release_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group release-groups into Album / Single/EP / Compilation / Live / Other, newest first."""
    buckets: dict[str, list[dict[str, Any]]] = {k: [] for k in DISCOGRAPHY_ORDER}
    seen: set[str] = set()
    for rg in release_groups:
        if rg["id"] in seen:
            continue
        seen.add(rg["id"])
        buckets[discography_bucket(rg)].append(summarize_release_group(rg))
    out = []
    for name in DISCOGRAPHY_ORDER:
        items = sorted(buckets[name], key=lambda r: (r["first_release_date"] or "0000"), reverse=True)
        if items:
            out.append({"type": name, "items": items})
    return out


def related_artists(artist: dict[str, Any], limit: int = 20) -> list[dict[str, Any]]:
    """Related artists from artist-artist relationships (members, collaborations, etc.)."""
    out: list[dict[str, Any]] = []
    seen: set[str] = {artist.get("id", "")}
    for rel in artist.get("relations") or []:
        if rel.get("target-type") != "artist":
            continue
        target = rel.get("artist") or {}
        tid = target.get("id")
        if not tid or tid in seen:
            continue
        seen.add(tid)
        out.append({
            "id": tid,
            "name": target.get("name", ""),
            "disambiguation": target.get("disambiguation") or None,
            "relation": rel.get("type"),
            "direction": rel.get("direction"),
        })
        if len(out) >= limit:
            break
    return out


def release_formats(release: dict[str, Any]) -> list[str]:
    return [m.get("format") or "Unknown" for m in release.get("media") or []]


def release_track_count(release: dict[str, Any]) -> int:
    if "track-count" in release and not release.get("media"):
        return int(release["track-count"])
    return sum(int(m.get("track-count") or len(m.get("tracks") or [])) for m in release.get("media") or [])


def _release_sort_key(release: dict[str, Any]) -> tuple:
    status = STATUS_RANK.get(release.get("status") or "", 0)
    formats = release_formats(release)
    fmt = min((FORMAT_RANK.get(f, 0) for f in formats), default=0) if formats else 0
    date = release.get("date") or ""
    # Incomplete dates (e.g. "1997") sort after precise dates of the same period
    # (a precise date is more trustworthy); unknown dates sort last.
    date_key = _pad_date(date)
    # Tie-break: worldwide/major-market releases, then id for determinism.
    country = COUNTRY_RANK.get(release.get("country") or "", 0)
    return (-status, -fmt, date_key, -country, release.get("id", ""))


def _pad_date(date: str) -> str:
    if not date:
        return "9999-99-99"
    parts = date.split("-")
    while len(parts) < 3:
        parts.append("99")
    return "-".join(parts)


def pick_canonical_release(releases: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Official > digital/CD > earliest date (ties: more precise date, then id for determinism)."""
    if not releases:
        return None
    return sorted(releases, key=_release_sort_key)[0]


def summarize_release(release: dict[str, Any]) -> dict[str, Any]:
    labels = release.get("label-info") or []
    return {
        "id": release["id"],
        "title": release.get("title", ""),
        "status": release.get("status"),
        "date": release.get("date") or None,
        "country": release.get("country"),
        "formats": release_formats(release),
        "track_count": release_track_count(release),
        "disambiguation": release.get("disambiguation") or None,
        "barcode": release.get("barcode") or None,
        "labels": [li.get("label", {}).get("name") for li in labels if li.get("label")],
        "catalog_numbers": [li["catalog-number"] for li in labels if li.get("catalog-number")],
    }


def tracklist(release: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten media/tracks into rows with disc and track numbers."""
    rows = []
    media = release.get("media") or []
    for medium in media:
        disc = int(medium.get("position") or 1)
        for t in medium.get("tracks") or []:
            rec = t.get("recording") or {}
            rows.append({
                "track_id": t["id"],
                "recording_id": rec.get("id"),
                "disc": disc,
                "disc_total": len(media),
                "position": int(t.get("position") or 0),
                "number": t.get("number"),
                "track_total": int(medium.get("track-count") or len(medium.get("tracks") or [])),
                "title": t.get("title") or rec.get("title", ""),
                "artist": artist_credit_string(t.get("artist-credit") or rec.get("artist-credit")),
                "length_ms": t.get("length") or rec.get("length"),
                "isrcs": rec.get("isrcs") or [],
                "medium_format": medium.get("format"),
                "medium_title": medium.get("title") or None,
            })
    return rows


def summarize_artist(a: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": a["id"],
        "name": a.get("name", ""),
        "sort_name": a.get("sort-name"),
        "type": a.get("type"),
        "country": a.get("country"),
        "disambiguation": a.get("disambiguation") or None,
        "score": a.get("score"),
        "life_span": a.get("life-span") or {},
        "genres": [g["name"] for g in sorted(a.get("genres") or [], key=lambda g: -g.get("count", 0))][:5],
    }


def summarize_recording_hit(r: dict[str, Any]) -> dict[str, Any]:
    releases = r.get("releases") or []
    best = pick_canonical_release(
        [{**rel, "media": rel.get("media") or []} for rel in releases]
    ) if releases else None
    return {
        "id": r["id"],
        "title": r.get("title", ""),
        "artist": artist_credit_string(r.get("artist-credit")),
        "artist_id": (artist_credit_ids(r.get("artist-credit")) or [None])[0],
        "length_ms": r.get("length"),
        "score": r.get("score"),
        "disambiguation": r.get("disambiguation") or None,
        "release": {
            "id": best["id"],
            "title": best.get("title"),
            "release_group_id": (best.get("release-group") or {}).get("id"),
            "date": best.get("date"),
        } if best else None,
    }


def normalize_title(s: str | None) -> str:
    return " ".join("".join(ch.lower() if ch.isalnum() else " " for ch in (s or "")).split())
