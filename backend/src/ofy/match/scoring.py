"""Pure match scoring between MusicBrainz data and YouTube Music results (no I/O).

All scores are in [0, 1].
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Any

from rapidfuzz import fuzz

ARTIST_MIN = 0.75  # below this artist similarity the result is almost surely another artist
ATV = "MUSIC_VIDEO_TYPE_ATV"  # "Art track": the official audio upload of a release

# Words that indicate a different *version* of a song. Penalized unless the MB title has them too.
VARIANT_WORDS = [
    "live", "remix", "rmx", "cover", "sped up", "speed up", "slowed", "reverb", "karaoke",
    "instrumental", "acoustic", "demo", "nightcore", "8d", "mashup", "tribute", "reprise",
    "a cappella", "acapella", "edit", "extended", "mix", "version", "remaster", "remastered",
    "radio edit", "unplugged", "bootleg", "lyrics", "lyric video", "audio",
]
# Of those, which are *strong* (a different performance/recording), vs weak (same recording).
STRONG_VARIANTS = {
    "live", "remix", "rmx", "cover", "sped up", "speed up", "slowed", "reverb", "karaoke",
    "instrumental", "acoustic", "demo", "nightcore", "8d", "mashup", "tribute", "a cappella",
    "acapella", "unplugged", "bootleg", "extended", "reprise",
}


@dataclass
class MBTrackQuery:
    track_id: str
    title: str
    artist: str
    length_ms: int | None
    disc: int = 1
    position: int = 1
    index: int = 1  # 1-based position across all discs (YT Music flattens discs)


@dataclass
class MBAlbumQuery:
    title: str
    artist: str
    year: str | None
    track_count: int
    primary_type: str | None = "Album"
    tracks: list[MBTrackQuery] = field(default_factory=list)


@dataclass
class YTCandidate:
    video_id: str
    title: str
    artists: list[str]
    album: str | None = None
    album_id: str | None = None
    duration: int | None = None  # seconds
    video_type: str | None = None
    track_number: int | None = None
    thumbnail: str | None = None
    source: str = "song"  # album | song

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScoredCandidate:
    candidate: YTCandidate
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {**self.candidate.to_dict(), "score": round(self.score, 4)}


# --- normalization -------------------------------------------------------------------------

_PAREN = re.compile(r"\s*[\(\[][^\)\]]*[\)\]]")
_DASH_SUFFIX = re.compile(r"\s+-\s+.*$")
_FEAT = re.compile(r"\s*[\(\[]?\b(feat\.?|ft\.?|featuring|with)\b.*$", re.I)


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def normalize(s: str | None) -> str:
    if not s:
        return ""
    s = strip_accents(s).lower()
    s = s.replace("&", " and ").replace("’", "'").replace("‐", "-").replace("–", "-").replace("—", "-")
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def core_title(s: str | None) -> str:
    """Title without parentheticals, ' - Remastered 2009' suffixes and featuring credits."""
    if not s:
        return ""
    s = _PAREN.sub("", s)
    s = _DASH_SUFFIX.sub("", s)
    s = _FEAT.sub("", s)
    return normalize(s)


def text_similarity(a: str | None, b: str | None) -> float:
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ca, cb = core_title(a), core_title(b)
    scores = [fuzz.token_sort_ratio(na, nb), fuzz.ratio(na, nb)]
    if ca and cb:
        core = fuzz.ratio(ca, cb)
        # Equal cores (e.g. "Exit Music (For a Film)" vs "Exit Music") are nearly equal,
        # but keep a small penalty so exact matches rank higher.
        scores.append(core * 0.95)
    return max(scores) / 100.0


def artist_similarity(mb_artist: str, yt_artists: list[str]) -> float:
    if not yt_artists:
        return 0.0
    joined = " ".join(yt_artists)
    best = max(
        [text_similarity(mb_artist, joined)]
        + [text_similarity(mb_artist, a) for a in yt_artists]
        + [fuzz.token_set_ratio(normalize(mb_artist), normalize(joined)) / 100.0 * 0.95]
    )
    # The primary MB artist appearing as one of the YT artists is good enough.
    primary = normalize(re.split(r"\s+(?:feat\.?|ft\.?|&|and|x|,|with)\s+", mb_artist, flags=re.I)[0])
    if primary and any(normalize(a) == primary for a in yt_artists):
        best = max(best, 0.95)
    return best


def variant_terms(title: str | None) -> set[str]:
    n = f" {normalize(title)} "
    return {w for w in VARIANT_WORDS if f" {w} " in n}


def variant_penalty(mb_title: str, yt_title: str, *, extra_yt_text: str = "") -> float:
    """Multiplier in (0, 1]: penalize live/remix/cover/sped up/karaoke… unless MB has it too."""
    mb_terms = variant_terms(mb_title)
    yt_terms = variant_terms(f"{yt_title} {extra_yt_text}")
    extra = yt_terms - mb_terms
    strong = extra & STRONG_VARIANTS
    if strong:
        return 0.45
    missing = (mb_terms - yt_terms) & STRONG_VARIANTS
    if missing:
        return 0.6
    return 1.0


def duration_similarity(mb_ms: int | None, yt_seconds: int | None, tolerance: float = 5.0) -> float:
    """1.0 within ±2s, gently down to 0.85 at ±tolerance, then fast decay to 0 at +20s."""
    if mb_ms is None or yt_seconds is None:
        return 0.5
    diff = abs(mb_ms / 1000.0 - yt_seconds)
    if diff <= 2:
        return 1.0
    if diff <= tolerance:
        return 1.0 - 0.15 * (diff - 2) / (tolerance - 2)
    if diff >= 20:
        return 0.0
    return 0.85 * (1 - (diff - tolerance) / (20 - tolerance))


def year_similarity(mb_year: str | None, yt_year: str | None) -> float:
    if not mb_year or not yt_year or not str(yt_year).isdigit():
        return 0.5
    d = abs(int(mb_year) - int(yt_year))
    return {0: 1.0, 1: 0.8, 2: 0.5}.get(d, 0.2)


def track_count_similarity(mb_count: int, yt_count: int | None) -> float:
    if not yt_count:
        return 0.5
    if mb_count == yt_count:
        return 1.0
    d = abs(mb_count - yt_count)
    return max(0.0, 1.0 - d / max(mb_count, yt_count) * 2)


# --- Strategy A: albums ------------------------------------------------------------------

def score_album(q: MBAlbumQuery, title: str, artists: list[str], year: str | None,
                yt_type: str | None = None, track_count: int | None = None) -> float:
    title_s = text_similarity(q.title, title)
    artist_s = artist_similarity(q.artist, artists)
    year_s = year_similarity(q.year, year)
    count_s = track_count_similarity(q.track_count, track_count)
    score = 0.4 * title_s + 0.3 * artist_s + 0.1 * year_s + 0.2 * count_s
    # Deluxe/live/remix editions of the same album are a worse fit than the plain one.
    score *= variant_penalty(q.title, title) ** 0.5
    if q.primary_type == "Album" and yt_type and yt_type.lower() in ("single",) and q.track_count > 3:
        score *= 0.8
    if artist_s < ARTIST_MIN:
        score *= 0.5
    return max(0.0, min(1.0, score))


def score_album_track(t: MBTrackQuery, c: YTCandidate) -> float:
    title_s = text_similarity(t.title, c.title)
    dur_s = duration_similarity(t.length_ms, c.duration)
    pos_s = 1.0 if c.track_number == t.index else (0.5 if c.track_number and abs(c.track_number - t.index) == 1 else 0.0)
    score = 0.55 * title_s + 0.3 * dur_s + 0.15 * pos_s
    score *= variant_penalty(t.title, c.title)
    if dur_s == 0.0:
        score *= 0.5
    return max(0.0, min(1.0, score))


COMPOSITE_SEP = "+"  # video ids of a composite match are joined with this


def composite_candidates(t: MBTrackQuery, yt_tracks: list[YTCandidate]) -> list[tuple[tuple[int, ...], YTCandidate, float]]:
    """MB sometimes merges several songs into one track ("A / B", e.g. hidden tracks) where
    YT Music lists them separately. Match such a track to consecutive YT tracks whose titles
    match each part; their audio is concatenated at download time."""
    parts = [p.strip() for p in re.split(r"\s+/\s+", t.title) if p.strip()]
    if len(parts) < 2:
        return []
    out = []
    n = len(parts)
    for start in range(0, len(yt_tracks) - n + 1):
        seq = yt_tracks[start:start + n]
        sims = [text_similarity(p, c.title) for p, c in zip(parts, seq)]
        if min(sims) < 0.85:
            continue
        durs = [c.duration for c in seq]
        total = sum(d for d in durs if d) if all(durs) else None
        if t.length_ms is None or total is None:
            dur_s = 0.5
        else:
            diff = t.length_ms / 1000 - total
            if abs(diff) <= 5:
                dur_s = 1.0
            elif diff > 0:
                dur_s = 0.7  # MB length longer: typical for hidden tracks preceded by silence
            else:
                dur_s = 0.0
        pos_s = 1.0 if seq[0].track_number == t.index else 0.0
        score = 0.6 * (sum(sims) / n) + 0.25 * dur_s + 0.15 * pos_s
        comp = YTCandidate(
            video_id=COMPOSITE_SEP.join(c.video_id for c in seq),
            title=" / ".join(c.title for c in seq),
            artists=seq[0].artists,
            album=seq[0].album,
            album_id=seq[0].album_id,
            duration=total,
            video_type=seq[0].video_type,
            track_number=seq[0].track_number,
            thumbnail=seq[0].thumbnail,
            source="album",
        )
        out.append((tuple(range(start, start + n)), comp, score))
    return out


def map_album_tracks(tracks: list[MBTrackQuery], yt_tracks: list[YTCandidate],
                     album_score: float) -> dict[str, list[ScoredCandidate]]:
    """Map MB tracks to YT album tracks one-to-one (greedy on the best pair scores).

    Returns per MB track the ranked candidates; the first is the assigned one (if any).
    Track confidence combines the pair score with the album score.
    """
    pairs: list[tuple[float, int, tuple[int, ...], YTCandidate]] = []
    per_track: dict[str, list[ScoredCandidate]] = {t.track_id: [] for t in tracks}
    for i, t in enumerate(tracks):
        for j, c in enumerate(yt_tracks):
            s = score_album_track(t, c)
            combined = 0.85 * s + 0.15 * album_score
            pairs.append((combined, i, (j,), c))
            per_track[t.track_id].append(ScoredCandidate(c, combined))
        for js, comp, s in composite_candidates(t, yt_tracks):
            combined = 0.85 * s + 0.15 * album_score
            pairs.append((combined, i, js, comp))
            per_track[t.track_id].append(ScoredCandidate(comp, combined))
    pairs.sort(key=lambda p: -p[0])
    used_t: set[int] = set()
    used_c: set[int] = set()
    assigned: dict[str, ScoredCandidate] = {}
    for s, i, js, c in pairs:
        if i in used_t or any(j in used_c for j in js) or s < 0.3:
            continue
        used_t.add(i)
        used_c.update(js)
        assigned[tracks[i].track_id] = ScoredCandidate(c, s)
    out: dict[str, list[ScoredCandidate]] = {}
    for t in tracks:
        ranked = sorted(per_track[t.track_id], key=lambda sc: -sc.score)
        a = assigned.get(t.track_id)
        if a:
            out[t.track_id] = ([a] + [sc for sc in ranked if sc.candidate.video_id != a.candidate.video_id])[:5]
        else:
            # Nothing could be assigned one-to-one: keep candidates for manual review only.
            out[t.track_id] = [ScoredCandidate(sc.candidate, min(sc.score, 0.29)) for sc in ranked[:5]]
    return out


# --- Strategy B: songs -------------------------------------------------------------------

def score_song(t: MBTrackQuery, album_title: str | None, c: YTCandidate) -> float:
    title_s = text_similarity(t.title, c.title)
    artist_s = artist_similarity(t.artist, c.artists)
    dur_s = duration_similarity(t.length_ms, c.duration)
    album_s = text_similarity(album_title, c.album) if album_title and c.album else 0.5
    score = 0.45 * title_s + 0.25 * artist_s + 0.2 * dur_s + 0.1 * album_s
    if c.video_type == ATV:
        score += 0.05
    elif c.video_type:  # OMV / UGC / podcast etc: video audio can contain intros/outros
        score -= 0.08
    score *= variant_penalty(t.title, c.title, extra_yt_text=c.album or "")
    if dur_s == 0.0:
        score *= 0.5
    if artist_s < ARTIST_MIN:
        score *= 0.5
    return max(0.0, min(1.0, score))


def rank_songs(t: MBTrackQuery, album_title: str | None, candidates: list[YTCandidate]) -> list[ScoredCandidate]:
    scored = [ScoredCandidate(c, score_song(t, album_title, c)) for c in candidates]
    scored.sort(key=lambda s: -s.score)
    return scored


def merge_candidates(*lists: list[ScoredCandidate], limit: int = 5) -> list[ScoredCandidate]:
    best: dict[str, ScoredCandidate] = {}
    for lst in lists:
        for sc in lst:
            prev = best.get(sc.candidate.video_id)
            if prev is None or sc.score > prev.score:
                best[sc.candidate.video_id] = sc
    return sorted(best.values(), key=lambda s: -s.score)[:limit]


# --- adapters from ytmusicapi dicts ------------------------------------------------------------

def _thumb(d: dict[str, Any]) -> str | None:
    thumbs = d.get("thumbnails") or (d.get("thumbnail") or {}).get("thumbnails") or []
    if isinstance(thumbs, list) and thumbs:
        return thumbs[0].get("url")
    return None


def candidate_from_ytm(d: dict[str, Any], *, source: str, album: str | None = None,
                       album_id: str | None = None, track_number: int | None = None) -> YTCandidate | None:
    vid = d.get("videoId")
    if not vid:
        return None
    alb = d.get("album")
    return YTCandidate(
        video_id=vid,
        title=d.get("title") or "",
        artists=[a.get("name", "") for a in d.get("artists") or [] if a.get("name")],
        album=album or (alb.get("name") if isinstance(alb, dict) else alb),
        album_id=album_id or (alb.get("id") if isinstance(alb, dict) else None),
        duration=d.get("duration_seconds"),
        video_type=d.get("videoType"),
        track_number=track_number if track_number is not None else d.get("trackNumber"),
        thumbnail=_thumb(d),
        source=source,
    )


def album_tracks_from_ytm(album: dict[str, Any], album_id: str,
                          audio_playlist: list[dict[str, Any]] | None = None) -> list[YTCandidate]:
    """YT album tracks, replacing music-video entries with their art-track equivalent
    from the album's audio playlist (same position, similar title)."""
    out: list[YTCandidate] = []
    tracks = album.get("tracks") or []
    for i, t in enumerate(tracks, start=1):
        if t.get("isAvailable") is False and not t.get("videoId"):
            continue
        number = t.get("trackNumber") or i
        if audio_playlist and t.get("videoType") != ATV and len(audio_playlist) >= i:
            alt = audio_playlist[i - 1]
            if alt.get("videoId") and alt.get("videoType") == ATV and text_similarity(alt.get("title"), t.get("title")) > 0.8:
                t = {**t, "videoId": alt["videoId"], "videoType": ATV,
                     "duration_seconds": alt.get("duration_seconds") or t.get("duration_seconds")}
        c = candidate_from_ytm(t, source="album", album=album.get("title"), album_id=album_id, track_number=number)
        if c:
            if not c.artists:
                c.artists = [a.get("name", "") for a in album.get("artists") or []]
            out.append(c)
    return out
