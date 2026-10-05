"""Path templating and filename sanitizing (pure functions)."""

from __future__ import annotations

import re
import string
import unicodedata
from pathlib import PurePosixPath
from typing import Any

ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
MAX_COMPONENT = 180  # bytes (UTF-8); most filesystems allow 255, leave room for .lrc/.part

TEMPLATE_FIELDS = {
    "albumartist", "artist", "album", "title", "year", "date", "originalyear", "disc",
    "disctotal", "track", "tracktotal", "ext", "media", "releasetype", "catalognumber",
    "label", "albumartistsort", "artistsort",
}

DEFAULT_TEMPLATE = "{albumartist}/{album}/{artist} - {title}.{ext}"
# Former defaults: a stored template equal to one of these is upgraded to DEFAULT_TEMPLATE.
LEGACY_DEFAULT_TEMPLATES = (
    "{albumartist}/{album}/{disc}-{track:02} - {title}.{ext}",
    "{albumartist}/{year} - {album}/{disc}-{track:02} - {title}.{ext}",
)

SAMPLE_VALUES: dict[str, Any] = {
    "albumartist": "Artist", "artist": "Artist", "album": "Album", "title": "Title", "year": "2000",
    "date": "2000-01-01", "originalyear": "2000", "disc": 1, "disctotal": 1, "track": 1,
    "tracktotal": 10, "ext": "mp3", "media": "CD", "releasetype": "album", "catalognumber": "CAT1",
    "label": "Label", "albumartistsort": "Artist", "artistsort": "Artist",
}


class TemplateError(ValueError):
    pass


def _truncate_bytes(s: str, limit: int) -> str:
    b = s.encode("utf-8")
    if len(b) <= limit:
        return s
    return b[:limit].decode("utf-8", errors="ignore")


def sanitize_component(name: str, *, max_bytes: int = MAX_COMPONENT, replacement: str = "_") -> str:
    """Make a single path component safe on Linux, macOS and Windows filesystems."""
    name = unicodedata.normalize("NFC", str(name))
    name = ILLEGAL_CHARS.sub(replacement, name)
    name = re.sub(r"\s+", " ", name).strip()
    # Trailing dots and spaces are illegal on Windows; leading dots would hide files.
    name = name.rstrip(". ").lstrip(". ")
    if not name:
        name = replacement
    if name.split(".")[0].upper() in WINDOWS_RESERVED:
        name = f"{name}{replacement}"
    if len(name.encode("utf-8")) > max_bytes:
        stem, dot, ext = name.rpartition(".")
        if dot and 0 < len(ext) <= 5 and stem:
            name = _truncate_bytes(stem, max_bytes - len(ext) - 1).rstrip(". ") + "." + ext
        else:
            name = _truncate_bytes(name, max_bytes).rstrip(". ")
    return name


def _sanitize_value(v: Any) -> Any:
    if isinstance(v, str):
        # A value may never introduce a directory separator.
        return ILLEGAL_CHARS.sub("_", v).strip()
    return v


class _Formatter(string.Formatter):
    def get_value(self, key, args, kwargs):
        if isinstance(key, int) or key not in TEMPLATE_FIELDS:
            raise TemplateError(f"unknown field {{{key}}}")
        return kwargs.get(key, "")

    def format_field(self, value, format_spec):
        if format_spec and isinstance(value, str):
            # e.g. {track:02} given as a string -> try numeric first
            if value.isdigit():
                return format(int(value), format_spec)
            return value
        if value is None:
            return ""
        return format(value, format_spec)


_formatter = _Formatter()


def render_template(template: str, values: dict[str, Any]) -> PurePosixPath:
    """Render a path template into a relative, sanitized path."""
    clean = {k: _sanitize_value(v) for k, v in values.items()}
    try:
        rendered = _formatter.format(template, **clean)
    except (KeyError, IndexError, ValueError) as e:
        if isinstance(e, TemplateError):
            raise
        raise TemplateError(str(e)) from e
    parts = [p for p in rendered.replace("\\", "/").split("/")]
    out = []
    for p in parts:
        if p.strip() in ("", ".", ".."):
            continue
        out.append(sanitize_component(p))
    if not out:
        raise TemplateError("template rendered to an empty path")
    return PurePosixPath(*out)


def validate_template(template: str) -> None:
    if not template.strip():
        raise TemplateError("template is empty")
    if template.strip().startswith("/"):
        raise TemplateError("template must be relative to the library root")
    if not template.endswith(".{ext}"):
        raise TemplateError("template must end with .{ext}")
    render_template(template, SAMPLE_VALUES)
