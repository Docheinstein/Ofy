"""Cover Art Archive client with an on-disk cache."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

import httpx

from ofy.config import env
from ofy.ratelimit import RateLimiter

log = logging.getLogger(__name__)

SIZES = ("250", "500", "1200")
NEGATIVE_TTL = 86400.0

# Image variants tried for each requested size, best first. The bool marks a variant smaller than
# requested: it is served but not cached, so a later request tries again for the proper size.
VARIANTS: dict[str, list[tuple[str, bool]]] = {
    "full": [("front", False), ("front-1200", True), ("front-500", True), ("front-250", True)],
    "1200": [("front-1200", False), ("front", False), ("front-500", True), ("front-250", True)],
    "500": [("front-500", False), ("front-1200", False), ("front-250", True)],
    "250": [("front-250", False), ("front-500", False)],
}
# Cover Art Archive redirects to a random archive.org storage node, and single nodes fail with 5xx
# now and then: retrying usually lands on a healthy one.
ATTEMPTS = 3
BACKOFF = 0.5  # seconds before the 2nd attempt, doubled for each further one
MAX_RETRY_AFTER = 10.0

_limiter = RateLimiter(0.25)
_client: httpx.AsyncClient | None = None
_sleep = asyncio.sleep


class CoverUnavailable(Exception):
    """The cover may exist but couldn't be fetched right now (server errors, network); not cached."""


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            headers={"User-Agent": env.user_agent}, timeout=30, follow_redirects=True
        )
    return _client


def _cache_path(kind: str, mbid: str, size: str) -> Path:
    return env.cover_cache_dir / f"{kind}-{mbid}-{size}.jpg"


def _retry_delay(attempt: int, resp: httpx.Response | None) -> float:
    delay = BACKOFF * 2**attempt
    if resp is not None and resp.status_code == 429:
        try:
            delay = max(delay, float(resp.headers.get("retry-after", delay)))
        except ValueError:
            pass
    return min(delay, MAX_RETRY_AFTER)


async def _get_with_retry(url: str) -> bytes | None:
    """Image bytes, or None when the server says it doesn't exist (404/400).

    Server errors, 429 and network errors are retried with exponential backoff; raises
    CoverUnavailable once all attempts failed.
    """
    for attempt in range(ATTEMPTS):
        resp: httpx.Response | None = None
        try:
            async with _limiter:
                resp = await _http().get(url)
        except httpx.HTTPError as e:
            reason = str(e) or type(e).__name__
        else:
            if resp.status_code == 200 and resp.content:
                return resp.content
            if resp.status_code in (404, 400):
                return None
            reason = f"HTTP {resp.status_code}"
        if attempt + 1 < ATTEMPTS:
            delay = _retry_delay(attempt, resp)
            log.info("cover art fetch failed %s (%s), retrying in %.1fs", url, reason, delay)
            await _sleep(delay)
        else:
            log.warning("cover art fetch failed %s (%s), giving up after %d attempts", url, reason, ATTEMPTS)
    raise CoverUnavailable(url)


async def fetch_front(kind: str, mbid: str, size: str = "1200") -> bytes | None:
    """Front cover for a release or release-group. ``size`` is 250, 500, 1200 or 'full'.

    Variants are tried best first (see VARIANTS), each with retries. Returns None when the
    release has no front cover; raises CoverUnavailable when one may exist but couldn't be fetched.
    """
    assert kind in ("release", "release-group")
    path = _cache_path(kind, mbid, size)
    neg = path.with_suffix(".404")
    if path.is_file():
        return path.read_bytes()
    if neg.is_file() and time.time() - neg.stat().st_mtime < NEGATIVE_TTL:
        return None
    unavailable = False
    for suffix, smaller in VARIANTS[size]:
        try:
            data = await _get_with_retry(f"{env.coverart_url}/{kind}/{mbid}/{suffix}")
        except CoverUnavailable:
            unavailable = True
            continue
        if data is None:
            continue
        if not smaller:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".part")
            tmp.write_bytes(data)
            tmp.replace(path)
        return data
    if unavailable:
        raise CoverUnavailable(f"{kind}/{mbid}")
    path.parent.mkdir(parents=True, exist_ok=True)
    neg.touch()
    return None


async def front_or_none(kind: str, mbid: str, size: str = "1200") -> bytes | None:
    """Like fetch_front, but a temporarily unavailable cover is just None."""
    try:
        return await fetch_front(kind, mbid, size)
    except CoverUnavailable:
        return None


async def front_for_release(release_id: str, release_group_id: str | None, size: str = "1200") -> bytes | None:
    """Release front cover, falling back to the release-group's cover. None if neither can be had."""
    data = await front_or_none("release", release_id, size)
    if data is None and release_group_id:
        data = await front_or_none("release-group", release_group_id, size)
    return data
