"""ffmpeg conversion to the configured output format."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

EXT = {"mp3": "mp3", "m4a": "m4a", "opus": "opus"}


class ConvertError(RuntimeError):
    pass


def ffmpeg_bin() -> str:
    p = shutil.which("ffmpeg")
    if not p:
        raise ConvertError("ffmpeg not found on PATH")
    return p


def probe_codec(path: Path) -> str | None:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    out = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=codec_name",
         "-of", "json", str(path)],
        capture_output=True, text=True, timeout=60,
    )
    try:
        return json.loads(out.stdout)["streams"][0]["codec_name"]
    except (KeyError, IndexError, json.JSONDecodeError):
        return None


def normalize_codec(acodec: str | None) -> str | None:
    if not acodec:
        return None
    a = acodec.lower()
    if a.startswith("mp4a") or a == "aac":
        return "aac"
    if a == "opus":
        return "opus"
    return a


def encode_args(fmt: str, src_codec: str | None, mp3_quality: str) -> tuple[list[str], bool]:
    """ffmpeg codec args for the output format, and whether this is a lossless remux."""
    if fmt == "mp3":
        q = ["-b:a", "320k"] if mp3_quality == "320" else ["-q:a", "0"]
        return ["-c:a", "libmp3lame", *q], False
    if fmt == "m4a":
        if src_codec == "aac":
            return ["-c:a", "copy", "-movflags", "+faststart"], True
        return ["-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart"], False
    if fmt == "opus":
        if src_codec == "opus":
            return ["-c:a", "copy"], True
        return ["-c:a", "libopus", "-b:a", "160k"], False
    raise ConvertError(f"unknown output format {fmt}")


def convert(sources: list[Path], dest: Path, fmt: str, *, src_codec: str | None, mp3_quality: str = "320") -> bool:
    """Convert (or remux) one or more source files into ``dest``.

    Multiple sources (composite matches) are concatenated and always re-encoded.
    Returns True if the audio stream was copied without re-encoding.
    """
    ff = ffmpeg_bin()
    if len(sources) == 1:
        codec_args, copied = encode_args(fmt, src_codec, mp3_quality)
        cmd = [ff, "-hide_banner", "-loglevel", "error", "-y", "-i", str(sources[0]),
               "-map", "0:a:0", "-vn", "-map_metadata", "-1", *codec_args]
    else:
        codec_args, _ = encode_args(fmt, None, mp3_quality)
        copied = False
        cmd = [ff, "-hide_banner", "-loglevel", "error", "-y"]
        for s in sources:
            cmd += ["-i", str(s)]
        inputs = "".join(f"[{i}:a:0]" for i in range(len(sources)))
        cmd += ["-filter_complex", f"{inputs}concat=n={len(sources)}:v=0:a=1[out]", "-map", "[out]",
                "-map_metadata", "-1", *codec_args]
    if fmt == "mp3":
        cmd += ["-id3v2_version", "4", "-write_xing", "1"]
    if fmt == "opus":
        cmd += ["-f", "opus"]
    if fmt == "m4a":
        cmd += ["-f", "ipod"]
    cmd.append(str(dest))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if proc.returncode != 0 or not dest.is_file() or dest.stat().st_size == 0:
        raise ConvertError(f"ffmpeg failed: {proc.stderr.strip()[-500:]}")
    return copied
