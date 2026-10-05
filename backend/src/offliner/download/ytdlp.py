"""Audio download through yt-dlp used as a library."""

from __future__ import annotations

import logging
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

FORMAT_SELECTORS = {
    # Prefer the codec we can keep without re-encoding, else the best audio available.
    "opus": "bestaudio[acodec=opus]/bestaudio",
    "m4a": "bestaudio[acodec^=mp4a]/bestaudio[ext=m4a]/bestaudio",
    "mp3": "bestaudio[acodec=opus]/bestaudio",
}


class DownloadError(RuntimeError):
    pass


@dataclass
class DownloadedAudio:
    path: Path
    video_id: str
    acodec: str | None
    ext: str
    duration: float | None
    abr: float | None


def js_runtimes() -> dict[str, dict]:
    """yt-dlp needs a JS runtime for YouTube player challenges; enable whichever is installed."""
    out: dict[str, dict] = {}
    for name in ("deno", "node", "bun"):
        p = shutil.which(name)
        if p:
            out[name] = {"path": p}
    return out


def base_options(cookies_path: str | None = None) -> dict[str, Any]:
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "retries": 3,
        "fragment_retries": 3,
        "socket_timeout": 30,
        "cachedir": False,
        "extractor_retries": 2,
    }
    rt = js_runtimes()
    if rt:
        opts["js_runtimes"] = rt
    if cookies_path and Path(cookies_path).is_file():
        opts["cookiefile"] = cookies_path
    return opts


def watch_url(video_id: str) -> str:
    return f"https://music.youtube.com/watch?v={video_id}"


def download_audio(video_id: str, dest_dir: Path, target_format: str, *,
                   cookies_path: str | None = None,
                   progress: Callable[[float], None] | None = None) -> DownloadedAudio:
    """Download the best audio stream for ``video_id`` into ``dest_dir`` (blocking)."""
    import yt_dlp

    dest_dir.mkdir(parents=True, exist_ok=True)

    def hook(d: dict[str, Any]) -> None:
        if progress is None:
            return
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if total:
                progress(min(0.999, d.get("downloaded_bytes", 0) / total))
        elif d.get("status") == "finished":
            progress(1.0)

    opts = {
        **base_options(cookies_path),
        "format": FORMAT_SELECTORS.get(target_format, "bestaudio"),
        "outtmpl": str(dest_dir / f"{video_id}.%(ext)s"),
        "progress_hooks": [hook],
        "overwrites": True,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(watch_url(video_id), download=True)
    except yt_dlp.utils.DownloadError as e:
        raise DownloadError(str(e).removeprefix("ERROR: ")) from e
    if info is None:
        raise DownloadError("yt-dlp returned no info")
    req = (info.get("requested_downloads") or [{}])[0]
    path = Path(req.get("filepath") or req.get("filename") or "")
    if not path.is_file():
        candidates = sorted(dest_dir.glob(f"{video_id}.*"))
        if not candidates:
            raise DownloadError("downloaded file not found")
        path = candidates[0]
    return DownloadedAudio(
        path=path,
        video_id=video_id,
        acodec=info.get("acodec") or req.get("acodec"),
        ext=info.get("ext") or path.suffix.lstrip("."),
        duration=info.get("duration"),
        abr=info.get("abr"),
    )


def stream_info(video_id: str, *, cookies_path: str | None = None) -> dict[str, Any]:
    """Resolve a direct audio stream URL (for the playback proxy) without downloading."""
    import yt_dlp

    opts = {**base_options(cookies_path), "format": "bestaudio[ext=m4a]/bestaudio[acodec=opus]/bestaudio",
            "skip_download": True}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(watch_url(video_id), download=False)
    except yt_dlp.utils.DownloadError as e:
        raise DownloadError(str(e).removeprefix("ERROR: ")) from e
    fmt = info.get("requested_formats", [info])[0] if info.get("requested_formats") else info
    return {
        "url": fmt.get("url") or info.get("url"),
        "headers": fmt.get("http_headers") or info.get("http_headers") or {},
        "ext": fmt.get("ext") or info.get("ext"),
        "acodec": fmt.get("acodec") or info.get("acodec"),
        "filesize": fmt.get("filesize") or fmt.get("filesize_approx"),
        "duration": info.get("duration"),
    }
