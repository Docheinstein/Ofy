"""Artist photos. MusicBrainz has none, so: the artist's Wikidata item (from MusicBrainz's wikidata
URL relationship when known, else found by its MusicBrainz artist ID, P434) and its image (P18),
served as a Wikimedia Commons thumbnail. Cached on disk like cover art.

Uses the regular Wikidata API (api.php); the SPARQL query service is rate-limited far more strictly."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from ofy.cache import cache_get, cache_set
from ofy.config import env
from ofy.ratelimit import RateLimiter

log = logging.getLogger(__name__)

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
COMMONS_FILEPATH = "https://commons.wikimedia.org/wiki/Special:FilePath/"
FOUND_TTL = 30 * 86400.0
MISSING_TTL = 7 * 86400.0  # artists without a photo: look again after a week

# Wikimedia rate-limits anonymous clients; one lookup per second keeps us well clear of 429s.
_limiter = RateLimiter(1.0)
_client: httpx.AsyncClient | None = None


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(headers={"User-Agent": env.user_agent}, timeout=20, follow_redirects=True)
    return _client


# --- pure helpers -------------------------------------------------------------------------------

def parse_search_qid(data: dict[str, Any]) -> str | None:
    """Wikidata item id from a ``list=search`` response for ``haswbstatement:P434=<mbid>``."""
    hits = (data.get("query") or {}).get("search") or []
    title = hits[0].get("title") if hits else None
    return title if title and title.startswith("Q") else None


def parse_image_filename(data: dict[str, Any]) -> str | None:
    """Commons file name from a ``wbgetclaims`` P18 response (preferred rank first, never deprecated)."""
    claims = (data.get("claims") or {}).get("P18") or []
    ranked = sorted(claims, key=lambda c: {"preferred": 0, "normal": 1}.get(c.get("rank"), 2))
    for c in ranked:
        if c.get("rank") == "deprecated":
            continue
        value = ((c.get("mainsnak") or {}).get("datavalue") or {}).get("value")
        if isinstance(value, str) and value:
            return value
    return None


def wikidata_id_from_artist(artist: dict[str, Any]) -> str | None:
    """Q-id from a MusicBrainz artist's ``wikidata`` URL relationship (inc=url-rels)."""
    for rel in artist.get("relations") or []:
        if rel.get("type") == "wikidata":
            qid = ((rel.get("url") or {}).get("resource") or "").rstrip("/").rsplit("/", 1)[-1]
            if qid.startswith("Q") and qid[1:].isdigit():
                return qid
    return None


def commons_thumb_url(filename: str, width: int) -> str:
    return f"{COMMONS_FILEPATH}{quote(filename.replace(' ', '_'))}?width={width}"


def retry_after_seconds(resp: httpx.Response, default: float = 2.0, cap: float = 10.0) -> float:
    try:
        return min(cap, max(0.0, float(resp.headers.get("retry-after", default))))
    except ValueError:
        return default


# --- fetching -----------------------------------------------------------------------------------

class RateLimited(Exception):
    """Wikimedia asked us to back off; requests are skipped until the cooldown ends."""


_cooldown_until = 0.0


async def _get(url: str, **kw) -> httpx.Response:
    """GET through the shared limiter. On 429/503 *all* Wikimedia requests pause for Retry-After
    (instead of retrying), as Wikimedia's API etiquette asks."""
    global _cooldown_until
    if time.monotonic() < _cooldown_until:
        raise RateLimited
    async with _limiter:
        r = await _http().get(url, **kw)
    if r.status_code in (429, 503):
        _cooldown_until = time.monotonic() + retry_after_seconds(r, default=30, cap=600)
        log.info("Wikimedia rate limit: pausing artist image lookups for %.0fs", _cooldown_until - time.monotonic())
        raise RateLimited
    return r


async def _wikidata(params: dict[str, Any]) -> dict[str, Any]:
    r = await _get(WIKIDATA_API, params={**params, "format": "json"})
    r.raise_for_status()
    return r.json()


async def find_image_filename(mbid: str, qid: str | None = None) -> str | None:
    """Commons file name for the artist, cached per MBID (independent of the requested size)."""
    key = f"artistimg:{mbid}"
    cached = cache_get(key)
    if cached is not None:
        return cached or None
    if not qid:
        qid = parse_search_qid(await _wikidata({
            "action": "query", "list": "search", "srsearch": f"haswbstatement:P434={mbid}", "srlimit": 1,
        }))
    filename = None
    if qid:
        filename = parse_image_filename(await _wikidata({"action": "wbgetclaims", "entity": qid, "property": "P18"}))
    cache_set(key, filename or "", FOUND_TTL if filename else MISSING_TTL)
    return filename


def _cache_path(mbid: str, size: str) -> Path:
    return env.cover_cache_dir / f"artist-{mbid}-{size}.jpg"


async def fetch_artist_image(mbid: str, size: str = "500", qid: str | None = None) -> bytes | None:
    """Artist photo bytes, or None when Wikidata/Commons has none (or it's temporarily unavailable)."""
    path = _cache_path(mbid, size)
    if path.is_file():
        return path.read_bytes()
    try:
        filename = await find_image_filename(mbid, qid)
        if not filename:
            return None
        r = await _get(commons_thumb_url(filename, int(size)))
    except RateLimited:
        return None  # transient: not cached, retried on a later request
    except (httpx.HTTPError, ValueError) as e:
        log.info("artist image lookup failed for %s: %s", mbid, e)
        return None
    if r.status_code != 200 or not r.headers.get("content-type", "").startswith("image/"):
        log.info("artist image download failed for %s: HTTP %s", mbid, r.status_code)
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    tmp.write_bytes(r.content)
    tmp.replace(path)
    return r.content
