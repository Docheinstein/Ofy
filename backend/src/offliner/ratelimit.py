"""Async rate limiting primitives."""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable


class RateLimiter:
    """Guarantees at least ``interval`` seconds between the *start* of consecutive acquisitions.

    The limiter is global per instance and safe for concurrent coroutines: callers are
    serialized by a lock, so N concurrent callers are spread out over N * interval seconds.
    ``clock`` and ``sleep`` are injectable for deterministic tests.
    """

    def __init__(
        self,
        interval: float,
        *,
        jitter: float = 0.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.interval = interval
        self.jitter = jitter
        self._clock = clock
        self._sleep = sleep
        self._lock = asyncio.Lock()
        self._last: float | None = None

    async def acquire(self) -> None:
        async with self._lock:
            now = self._clock()
            if self._last is not None:
                wait = self._last + self.interval - now
                if self.jitter:
                    wait += random.uniform(0, self.jitter)
                if wait > 0:
                    await self._sleep(wait)
                    now = self._clock()
            self._last = now

    async def __aenter__(self) -> RateLimiter:
        await self.acquire()
        return self

    async def __aexit__(self, *exc) -> None:
        return None
