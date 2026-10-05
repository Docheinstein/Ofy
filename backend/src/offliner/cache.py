"""Tiny JSON response cache stored in SQLite with per-entry TTL."""

from __future__ import annotations

import json
import time
from typing import Any

from sqlmodel import delete

from offliner.db import CacheEntry, session


def cache_get(key: str) -> Any | None:
    with session() as s:
        row = s.get(CacheEntry, key)
        if row is None:
            return None
        if row.expires_at < time.time():
            s.delete(row)
            s.commit()
            return None
        return json.loads(row.value)


def cache_set(key: str, value: Any, ttl: float) -> None:
    with session() as s:
        row = s.get(CacheEntry, key) or CacheEntry(key=key, value="", expires_at=0)
        row.value = json.dumps(value)
        row.expires_at = time.time() + ttl
        s.add(row)
        s.commit()


def cache_purge_expired() -> None:
    with session() as s:
        s.exec(delete(CacheEntry).where(CacheEntry.expires_at < time.time()))  # type: ignore[call-overload]
        s.commit()


def cache_delete(key: str) -> None:
    with session() as s:
        row = s.get(CacheEntry, key)
        if row is not None:
            s.delete(row)
            s.commit()
