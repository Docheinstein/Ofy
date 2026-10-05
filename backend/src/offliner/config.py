"""Bootstrap configuration (environment) and runtime settings (persisted, editable from the UI)."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from offliner import __version__

USER_AGENT = f"Offliner/{__version__} ( https://github.com/offliner/offliner )"


def _env(name: str, default: str) -> str:
    return os.environ.get(f"OFFLINER_{name}", default)


def default_data_dir() -> Path:
    """Per-user app data: $XDG_DATA_HOME/offliner (~/.local/share/offliner), %APPDATA%\\Offliner on Windows."""
    if os.name == "nt" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "Offliner"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Offliner"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "offliner"


def default_library_dir() -> Path:
    return Path.home() / "Music" / "Offliner"


def default_static_dir() -> Path:
    """The built frontend: <repo>/frontend/dist next to backend/src/offliner."""
    return Path(__file__).resolve().parents[3] / "frontend" / "dist"


@dataclass(frozen=True)
class Env:
    """Process-level configuration read once from environment variables."""

    data_dir: Path = field(default_factory=lambda: Path(_env("DATA_DIR", str(default_data_dir()))).expanduser().resolve())
    default_library: Path = field(default_factory=lambda: Path(_env("LIBRARY_DIR", str(default_library_dir()))).expanduser().resolve())
    host: str = field(default_factory=lambda: _env("HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(_env("PORT", "8080")))
    static_dir: Path = field(default_factory=lambda: Path(_env("STATIC_DIR", str(default_static_dir()))).expanduser().resolve())
    musicbrainz_url: str = field(default_factory=lambda: _env("MUSICBRAINZ_URL", "https://musicbrainz.org/ws/2"))
    coverart_url: str = field(default_factory=lambda: _env("COVERART_URL", "https://coverartarchive.org"))
    contact: str = field(default_factory=lambda: _env("CONTACT", ""))
    scan_on_startup: bool = field(default_factory=lambda: _env("SCAN_ON_STARTUP", "1") == "1")
    start_workers: bool = field(default_factory=lambda: _env("START_WORKERS", "1") == "1")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "offliner.db"

    @property
    def tmp_dir(self) -> Path:
        return self.data_dir / "tmp"

    @property
    def cover_cache_dir(self) -> Path:
        return self.data_dir / "covers"

    @property
    def user_agent(self) -> str:
        if self.contact:
            return f"Offliner/{__version__} ( {self.contact} )"
        return USER_AGENT


env = Env()


class Settings(BaseModel):
    """User-editable settings; stored as JSON in the database."""

    library_path: str = Field(default_factory=lambda: str(env.default_library))
    output_format: Literal["mp3", "m4a", "opus"] = "mp3"
    mp3_quality: Literal["320", "v0"] = "320"
    path_template: str = "{albumartist}/{year} - {album}/{disc}-{track:02} - {title}.{ext}"  # see download.paths
    concurrency: int = Field(default=2, ge=1, le=8)
    match_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    lyrics_fetch: bool = True
    lyrics_prefer_synced: bool = True
    lyrics_embed: bool = True
    lrclib_url: str = "https://lrclib.net"
    cookies_path: str = ""
    max_retries: int = Field(default=3, ge=0, le=10)
