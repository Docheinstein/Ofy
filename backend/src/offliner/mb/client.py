"""MusicBrainz WS/2 JSON client: strict 1 req/s global limit, descriptive UA, SQLite cache."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import urlencode

import httpx

from offliner.cache import cache_get, cache_set
from offliner.config import env
from offliner.ratelimit import RateLimiter

log = logging.getLogger(__name__)

DAY = 86400.0
RELEASE_INC = "recordings+artist-credits+labels+isrcs+genres+release-groups+media"


class MusicBrainzError(RuntimeError):
    pass


class NotFound(MusicBrainzError):
    pass


class MusicBrainzClient:
    def __init__(
        self,
        base_url: str | None = None,
        *,
        limiter: RateLimiter | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = (base_url or env.musicbrainz_url).rstrip("/")
        # One request per second, globally. A little margin avoids edge-of-window 503s.
        self.limiter = limiter or RateLimiter(1.05)
        self._client = httpx.AsyncClient(
            headers={"User-Agent": env.user_agent, "Accept": "application/json"},
            timeout=30,
            transport=transport,
            follow_redirects=True,
        )
        self.network_calls = 0

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get(self, path: str, params: dict[str, Any] | None = None, *, ttl: float = 7 * DAY,
                  fresh: bool = False) -> dict[str, Any]:
        params = {k: v for k, v in (params or {}).items() if v is not None}
        params["fmt"] = "json"
        query = urlencode(sorted(params.items()))
        key = f"mb:{path}?{query}"
        if not fresh:
            cached = cache_get(key)
            if cached is not None:
                return cached
        url = f"{self.base_url}/{path.lstrip('/')}"
        delay = 2.0
        for attempt in range(5):
            async with self.limiter:
                self.network_calls += 1
                try:
                    resp = await self._client.get(url, params=params)
                except httpx.HTTPError as e:
                    log.warning("MusicBrainz request failed (%s): %s", url, e)
                    resp = None
            if resp is not None:
                if resp.status_code == 200:
                    data = resp.json()
                    cache_set(key, data, ttl)
                    return data
                if resp.status_code == 404:
                    raise NotFound(path)
                if resp.status_code not in (429, 500, 502, 503, 504):
                    raise MusicBrainzError(f"{resp.status_code} for {path}: {resp.text[:200]}")
            await asyncio.sleep(delay * (attempt + 1))
        raise MusicBrainzError(f"MusicBrainz unavailable for {path}")

    # --- typed helpers -------------------------------------------------------------------

    async def search(self, entity: str, query: str, limit: int = 25, offset: int = 0) -> dict[str, Any]:
        return await self.get(entity, {"query": query, "limit": limit, "offset": offset}, ttl=DAY)

    async def artist(self, mbid: str) -> dict[str, Any]:
        return await self.get(f"artist/{mbid}", {"inc": "artist-rels+genres+url-rels"}, ttl=7 * DAY)

    async def browse_release_groups(self, artist_mbid: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        offset = 0
        while True:
            data = await self.get(
                "release-group", {"artist": artist_mbid, "limit": 100, "offset": offset}, ttl=3 * DAY
            )
            groups = data.get("release-groups", [])
            out.extend(groups)
            offset += len(groups)
            if not groups or offset >= data.get("release-group-count", 0) or offset >= 500:
                return out

    async def release_group(self, mbid: str) -> dict[str, Any]:
        return await self.get(f"release-group/{mbid}", {"inc": "artist-credits+genres"}, ttl=7 * DAY)

    async def browse_releases(self, release_group_mbid: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        offset = 0
        while True:
            data = await self.get(
                "release",
                {"release-group": release_group_mbid, "inc": "media+labels", "limit": 100, "offset": offset},
                ttl=3 * DAY,
            )
            rels = data.get("releases", [])
            out.extend(rels)
            offset += len(rels)
            if not rels or offset >= data.get("release-count", 0) or offset >= 300:
                return out

    async def release(self, mbid: str, *, fresh: bool = False) -> dict[str, Any]:
        """Full release with everything needed for tagging, in a single request."""
        return await self.get(f"release/{mbid}", {"inc": RELEASE_INC}, ttl=7 * DAY, fresh=fresh)

    async def recording(self, mbid: str) -> dict[str, Any]:
        return await self.get(f"recording/{mbid}", {"inc": "releases+artist-credits+release-groups+media"},
                              ttl=7 * DAY)


_client: MusicBrainzClient | None = None


def get_mb() -> MusicBrainzClient:
    global _client
    if _client is None:
        _client = MusicBrainzClient()
    return _client
