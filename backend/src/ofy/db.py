"""SQLite persistence via SQLModel."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import event
from sqlmodel import Field, Session, SQLModel, create_engine, select

from ofy.config import Settings, env, migrate_legacy_data_dir


class CacheEntry(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value: str
    expires_at: float = Field(index=True)


class SettingRow(SQLModel, table=True):
    id: int = Field(default=1, primary_key=True)
    data: str = "{}"


class Album(SQLModel, table=True):
    release_id: str = Field(primary_key=True)
    release_group_id: str = Field(index=True)
    title: str
    artist: str
    artist_id: str | None = None
    year: str | None = None
    track_count: int = 0
    folder: str | None = None
    updated_at: float = Field(default_factory=time.time)


class Track(SQLModel, table=True):
    # MusicBrainz *release track* id (unique per position on a release)
    track_id: str = Field(primary_key=True)
    recording_id: str = Field(index=True)
    release_id: str = Field(index=True)
    release_group_id: str = Field(index=True)
    disc: int = 1
    position: int = 1
    title: str = ""
    artist: str = ""
    length_ms: int | None = None
    # none | queued | downloading | done | failed | needs_review
    status: str = Field(default="none", index=True)
    stage: str | None = None
    progress: float = 0.0
    file_path: str | None = None
    file_format: str | None = None
    # none | synced | plain | instrumental | not_found
    lyrics_status: str = "none"
    lyrics_path: str | None = None
    video_id: str | None = None
    match_score: float | None = None
    match_source: str | None = None  # album | song | manual
    candidates: str = "[]"  # JSON list of top candidates
    error: str | None = None
    updated_at: float = Field(default_factory=time.time)


class SyncSelection(SQLModel, table=True):
    """Something chosen to be kept on the sync remote. Selecting an artist or album covers
    every track below it, including ones downloaded later."""

    kind: str = Field(primary_key=True)  # artist (MusicBrainz artist id) | album (release id) | track
    ref_id: str = Field(primary_key=True)
    title: str = ""
    subtitle: str = ""
    created_at: float = Field(default_factory=time.time)


class Job(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    kind: str  # match_album | download | retag | lyrics
    track_id: str | None = Field(default=None, index=True)
    release_id: str | None = Field(default=None, index=True)
    # pending | running | done | failed
    status: str = Field(default="pending", index=True)
    attempts: int = 0
    next_run_at: float = Field(default_factory=time.time)
    error: str | None = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)


_engine = None


def get_engine():
    global _engine
    if _engine is None:
        migrate_legacy_data_dir()
        env.data_dir.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(
            f"sqlite:///{env.db_path}", connect_args={"check_same_thread": False, "timeout": 30}
        )

        @event.listens_for(_engine, "connect")
        def _pragmas(dbapi_conn, _record):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.close()

        SQLModel.metadata.create_all(_engine)
    return _engine


def set_engine(engine) -> None:
    """Used by tests to point at an in-memory/temporary database."""
    global _engine
    _engine = engine
    SQLModel.metadata.create_all(engine)


@contextmanager
def session() -> Iterator[Session]:
    with Session(get_engine(), expire_on_commit=False) as s:
        yield s


def load_settings() -> Settings:
    with session() as s:
        row = s.get(SettingRow, 1)
        data: dict[str, Any] = json.loads(row.data) if row else {}
    return Settings.model_validate(data)


def save_settings(settings: Settings) -> Settings:
    with session() as s:
        row = s.get(SettingRow, 1) or SettingRow(id=1)
        row.data = settings.model_dump_json()
        s.add(row)
        s.commit()
    return settings


def recover_interrupted_jobs() -> int:
    """Jobs left 'running' by a crash/restart go back to pending."""
    with session() as s:
        jobs = s.exec(select(Job).where(Job.status == "running")).all()
        for j in jobs:
            j.status = "pending"
            j.next_run_at = time.time()
            s.add(j)
        tracks = s.exec(select(Track).where(Track.status == "downloading")).all()
        for t in tracks:
            t.status = "queued"
            t.stage = None
            t.progress = 0
            s.add(t)
        s.commit()
        return len(jobs)
