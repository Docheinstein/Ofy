"""Live matching against MusicBrainz + YouTube Music. Run with: pytest -m network"""

import pytest

from ofy.match.__main__ import resolve_release
from ofy.match.engine import match_release

pytestmark = pytest.mark.network

ALBUMS = [("Radiohead", "OK Computer"), ("Daft Punk", "Discovery"), ("Adele", "25"), ("Nirvana", "Nevermind")]


@pytest.mark.parametrize("artist,album", ALBUMS)
async def test_official_album_matches(tmp_db, artist, album):
    release = await resolve_release(artist, album)
    result = await match_release(release, 0.7)
    assert result.album and result.album["score"] >= 0.85
    scores = [m.score for m in result.tracks.values()]
    assert sum(s >= 0.7 for s in scores) / len(scores) >= 0.95
