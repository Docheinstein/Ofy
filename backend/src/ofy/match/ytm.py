"""Throttled, cached access to YouTube Music through ytmusicapi.

ytmusicapi is synchronous, so calls run in a worker thread. A global limiter with jitter
keeps us from hammering YouTube even with several concurrent download jobs.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

from ofy.cache import cache_get, cache_set
from ofy.ratelimit import RateLimiter

log = logging.getLogger(__name__)

TTL = 3 * 86400.0


class YTMusicService:
    def __init__(self, interval: float = 1.0, jitter: float = 0.6) -> None:
        self.limiter = RateLimiter(interval, jitter=jitter)
        self._yt = None
        self._lock = threading.Lock()
        self.network_calls = 0

    def _client(self):
        with self._lock:
            if self._yt is None:
                from ytmusicapi import YTMusic

                self._yt = YTMusic()
            return self._yt

    async def _call(self, key: str, fn_name: str, *args, **kwargs) -> Any:
        cached = cache_get(key)
        if cached is not None:
            return cached
        delay = 2.0
        last: Exception | None = None
        for attempt in range(3):
            async with self.limiter:
                self.network_calls += 1
                try:
                    result = await asyncio.to_thread(lambda: getattr(self._client(), fn_name)(*args, **kwargs))
                    break
                except Exception as e:  # ytmusicapi raises plain Exceptions on HTTP errors
                    last = e
                    log.warning("ytmusicapi %s failed (attempt %d): %s", fn_name, attempt + 1, e)
            await asyncio.sleep(delay * (attempt + 1))
        else:
            raise RuntimeError(f"YouTube Music {fn_name} failed: {last}")
        cache_set(key, result, TTL)
        return result

    async def search_albums(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        return await self._call(f"ytm:search:albums:{query.lower()}", "search", query, filter="albums", limit=limit)

    async def search_songs(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        return await self._call(f"ytm:search:songs:{query.lower()}", "search", query, filter="songs", limit=limit)

    async def get_album(self, browse_id: str) -> dict[str, Any]:
        data = await self._call(f"ytm:album:{browse_id}", "get_album", browse_id)
        return data

    async def get_playlist_tracks(self, playlist_id: str) -> list[dict[str, Any]]:
        key = f"ytm:playlist:{playlist_id}"
        cached = cache_get(key)
        if cached is not None:
            return cached
        data = await self._call(key + ":raw", "get_playlist", playlist_id, limit=200)
        tracks = data.get("tracks") or []
        for t in tracks:
            t.pop("thumbnails", None)
        cache_set(key, tracks, TTL)
        return tracks


_service: YTMusicService | None = None


def get_ytm() -> YTMusicService:
    global _service
    if _service is None:
        _service = YTMusicService()
    return _service
