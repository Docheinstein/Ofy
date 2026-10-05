"""CLI: python -m offliner.match "<artist>" "<album>" [--threshold 0.7] [--release MBID]

Prints the chosen YouTube Music album and per-track matches with confidence scores.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from offliner.db import load_settings
from offliner.match.engine import album_query_from_release, match_release
from offliner.mb import logic
from offliner.mb.client import get_mb


def _lucene(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


async def resolve_release(artist: str, album: str) -> dict:
    mb = get_mb()
    data = await mb.get("release-group", {
        "query": f'releasegroup:"{_lucene(album)}" AND artist:"{_lucene(artist)}"', "limit": 10,
    })
    groups = data.get("release-groups", [])
    if not groups:
        raise SystemExit(f"No MusicBrainz release group found for {artist} – {album}")

    def rank(rg):
        exact = logic.normalize_title(rg.get("title")) == logic.normalize_title(album)
        is_album = rg.get("primary-type") == "Album" and not rg.get("secondary-types")
        return (-int(exact), -int(is_album), -int(rg.get("score", 0)))

    rg = sorted(groups, key=rank)[0]
    releases = await mb.browse_releases(rg["id"])
    canonical = logic.pick_canonical_release(releases)
    if canonical is None:
        raise SystemExit("Release group has no releases")
    return await mb.release(canonical["id"])


async def run(artist: str, album: str, threshold: float, release_id: str | None) -> int:
    mb = get_mb()
    release = await mb.release(release_id) if release_id else await resolve_release(artist, album)
    q = album_query_from_release(release)
    print(f"MusicBrainz: {q.artist} – {q.title} ({q.year}) · {q.track_count} tracks · release {release['id']}")
    result = await match_release(release, threshold)
    if result.album:
        a = result.album
        print(f"YT Music album: {a['title']} ({a.get('year')}) · {a.get('track_count')} tracks · "
              f"browseId {a['browse_id']} · album score {a['score']:.2f}")
    else:
        print("YT Music album: none found (falling back to per-song search)")
    print()
    print(f"{'#':>5}  {'MB title':<36} {'YT title':<36} {'video':<11} {'src':<5} {'dur Δ':>5} {'score':>5}")
    ok = 0
    for t in q.tracks:
        m = result.tracks[t.track_id]
        flag = "OK " if m.score >= threshold else "LOW"
        if m.score >= threshold:
            ok += 1
        if m.best:
            c = m.best.candidate
            delta = "" if (c.duration is None or t.length_ms is None) else f"{c.duration - t.length_ms / 1000:+.0f}s"
            print(f"{t.disc}-{t.position:02d}  {t.title[:36]:<36} {c.title[:36]:<36} {c.video_id:<11} "
                  f"{m.source or '':<5} {delta:>5} {m.score:5.2f} {flag}")
        else:
            print(f"{t.disc}-{t.position:02d}  {t.title[:36]:<36} {'—':<36} {'':<11} {'':<5} {'':>5} {0:5.2f} LOW")
    pct = 100.0 * ok / max(1, len(q.tracks))
    print(f"\n{ok}/{len(q.tracks)} tracks above threshold {threshold:.2f} ({pct:.0f}%)")
    await mb.aclose()
    return 0 if pct >= 95 else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m offliner.match", description=__doc__)
    p.add_argument("artist")
    p.add_argument("album")
    p.add_argument("--threshold", type=float, default=None)
    p.add_argument("--release", help="Use this MusicBrainz release id instead of searching")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)
    threshold = args.threshold if args.threshold is not None else load_settings().match_threshold
    return asyncio.run(run(args.artist, args.album, threshold, args.release))


if __name__ == "__main__":
    sys.exit(main())
