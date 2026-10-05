"""Verify a downloaded album folder against MusicBrainz.

    uv run python scripts/verify_album.py "<album folder>" <release-mbid> [--format mp3|m4a|opus]

Reads every audio file with mutagen and asserts that the required tags are present, that all
MusicBrainz ids equal the source MBIDs, that a front cover is embedded, and (for mp3) that the
tag is ID3v2.4. Also checks cover.jpg and lyrics sidecars. Exits non-zero on any failure.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from mutagen.id3 import ID3

from ofy.mb.client import MusicBrainzClient
from ofy.mb import logic
from ofy.tagging.model import build_tag_model
from ofy.tagging.writers import read_fields

REQUIRED = [
    "title", "artist", "artists", "album", "albumartist", "artistsort", "albumartistsort",
    "tracknumber", "totaltracks", "discnumber", "totaldiscs", "date", "originaldate", "genre",
    "label", "isrc", "media", "releasetype", "releasestatus", "releasecountry", "length",
    "musicbrainz_recordingid", "musicbrainz_trackid", "musicbrainz_albumid",
    "musicbrainz_releasegroupid", "musicbrainz_artistid", "musicbrainz_albumartistid",
    "youtube_video_id", "~cover",
]
EXTS = {"mp3": ".mp3", "m4a": ".m4a", "opus": ".opus"}


async def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("folder", type=Path)
    p.add_argument("release_id")
    p.add_argument("--format", default="mp3", choices=list(EXTS))
    args = p.parse_args()

    mb = MusicBrainzClient()
    release = await mb.release(args.release_id)
    await mb.aclose()
    rows = logic.tracklist(release)
    files = sorted(args.folder.glob(f"*{EXTS[args.format]}"))
    errors: list[str] = []

    def check(cond: bool, msg: str) -> None:
        if not cond:
            errors.append(msg)

    check(len(files) == len(rows), f"expected {len(rows)} files, found {len(files)}")
    check((args.folder / "cover.jpg").is_file(), "cover.jpg missing")
    by_track: dict[str, Path] = {}
    for f in files:
        fields = read_fields(f)
        name = f.name
        if args.format == "mp3":
            check(ID3(f).version == (2, 4, 0), f"{name}: not ID3v2.4 ({ID3(f).version})")
        for k in REQUIRED:
            check(bool(fields.get(k)), f"{name}: missing {k}")
        tid = (fields.get("musicbrainz_trackid") or [""])[0]
        by_track[tid] = f
        try:
            expected = build_tag_model(release, tid)
        except KeyError:
            errors.append(f"{name}: release track id {tid!r} not on release")
            continue
        check(fields.get("musicbrainz_recordingid") == [expected.musicbrainz_recordingid], f"{name}: recording id")
        check(fields.get("musicbrainz_albumid") == [release["id"]], f"{name}: release id")
        check(fields.get("musicbrainz_releasegroupid") == [expected.musicbrainz_releasegroupid], f"{name}: rg id")
        check(fields.get("musicbrainz_artistid") == expected.musicbrainz_artistids, f"{name}: artist ids")
        check(fields.get("musicbrainz_albumartistid") == expected.musicbrainz_albumartistids, f"{name}: album artist ids")
        check(fields.get("title") == [expected.title], f"{name}: title {fields.get('title')} != {expected.title}")
        check(fields.get("tracknumber") == [str(expected.tracknumber)], f"{name}: track number")
        check(fields.get("totaltracks") == [str(expected.totaltracks)], f"{name}: total tracks")
        check(fields.get("discnumber") == [str(expected.discnumber)], f"{name}: disc number")
        check(fields.get("date") == [expected.date], f"{name}: date")
        check(fields.get("originaldate") == [expected.originaldate], f"{name}: originaldate")
        check(fields.get("isrc") == expected.isrcs[:1], f"{name}: isrc")
        lrc, txt = f.with_suffix(".lrc"), f.with_suffix(".txt")
        status = "synced" if lrc.is_file() else "plain" if txt.is_file() else "none"
        embedded = "embedded" if fields.get("lyrics") else "-"
        print(f"  ok  {name:<45} lyrics={status:<6} {embedded}")
    missing = {r["track_id"] for r in rows} - set(by_track)
    check(not missing, f"tracks without a file: {sorted(missing)}")
    if errors:
        print("\nFAILED:")
        for e in errors:
            print("  -", e)
        return 1
    print(f"\nAll {len(files)} files verified ({args.format}).")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
