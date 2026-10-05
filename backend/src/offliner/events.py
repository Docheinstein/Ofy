"""In-process pub/sub used to push live progress over WebSocket."""

from __future__ import annotations

import asyncio
import json
from typing import Any


class EventHub:
    def __init__(self) -> None:
        self._queues: set[asyncio.Queue[str]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue[str]:
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=1000)
        self._queues.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[str]) -> None:
        self._queues.discard(q)

    def publish(self, event: dict[str, Any]) -> None:
        """Thread-safe: may be called from worker threads (yt-dlp progress hooks)."""
        msg = json.dumps(event)
        loop = self._loop
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if loop is not None and running is not loop:
            loop.call_soon_threadsafe(self._fanout, msg)
        else:
            self._fanout(msg)

    def _fanout(self, msg: str) -> None:
        for q in list(self._queues):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                pass


hub = EventHub()
