"""Cover Art Archive client with an on-disk cache."""

from __future__ import annotations

import logging
import time
from pathlib import Path

import httpx

from offliner.config import env
from offliner.ratelimit import RateLimiter

log = logging.getLogger(__name__)

SIZES = ("250", "500", "1200")
NEGATIVE_TTL = 86400.0

_limiter = RateLimiter(0.25)
_client: httpx.AsyncClient | None = None


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            headers={"User-Agent": env.user_agent}, timeout=30, follow_redirects=True
        )
    return _client


def _cache_path(kind: str, mbid: str, size: str) -> Path:
    return env.cover_cache_dir / f"{kind}-{mbid}-{size}.jpg"


async def fetch_front(kind: str, mbid: str, size: str = "1200") -> bytes | None:
    """Front cover for a release or release-group. ``size`` is 250, 500, 1200 or 'full'.

    For size 1200 falls back to the original image if no 1200px thumbnail exists.
    """
    assert kind in ("release", "release-group")
    path = _cache_path(kind, mbid, size)
    neg = path.with_suffix(".404")
    if path.is_file():
        return path.read_bytes()
    if neg.is_file() and time.time() - neg.stat().st_mtime < NEGATIVE_TTL:
        return None
    suffixes = [f"front-{size}"] if size != "full" else ["front"]
    if size == "1200":
        suffixes.append("front")
    data: bytes | None = None
    for suffix in suffixes:
        url = f"{env.coverart_url}/{kind}/{mbid}/{suffix}"
        try:
            async with _limiter:
                resp = await _http().get(url)
        except httpx.HTTPError as e:
            log.warning("cover art fetch failed %s: %s", url, e)
            return None  # transient: don't negative-cache
        if resp.status_code == 200 and resp.content:
            data = resp.content
            break
        if resp.status_code not in (404, 400):
            return None
    path.parent.mkdir(parents=True, exist_ok=True)
    if data is None:
        neg.touch()
        return None
    tmp = path.with_suffix(".part")
    tmp.write_bytes(data)
    tmp.replace(path)
    return data


async def front_for_release(release_id: str, release_group_id: str | None, size: str = "1200") -> bytes | None:
    """Release front cover, falling back to the release-group's cover."""
    data = await fetch_front("release", release_id, size)
    if data is None and release_group_id:
        data = await fetch_front("release-group", release_group_id, size)
    return data
