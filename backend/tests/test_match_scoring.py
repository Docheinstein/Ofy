from ofy.match import scoring
from ofy.match.engine import album_query_from_release
from ofy.match.scoring import MBAlbumQuery, MBTrackQuery, YTCandidate


def test_normalize_and_similarity():
    assert scoring.normalize("Exit Music (For A Film)") == "exit music for a film"
    assert scoring.text_similarity("Exit Music (for a Film)", "Exit Music (For A Film)") == 1.0
    assert scoring.text_similarity("Beyoncé", "Beyonce") == 1.0
    assert scoring.text_similarity("Airbag", "Airbag - Remastered 2009") > 0.9
    assert scoring.text_similarity("Airbag", "Karma Police") < 0.5


def test_artist_similarity_handles_featuring():
    assert scoring.artist_similarity("Daft Punk feat. Romanthony", ["Daft Punk"]) >= 0.95
    assert scoring.artist_similarity("Radiohead", ["Radiohead"]) == 1.0
    assert scoring.artist_similarity("Radiohead", ["MONTROPOLIS"]) < 0.5


def test_duration_similarity_tolerance():
    assert scoring.duration_similarity(200_000, 201) == 1.0
    assert 0.85 <= scoring.duration_similarity(200_000, 205) < 1.0
    assert scoring.duration_similarity(200_000, 230) == 0.0
    assert scoring.duration_similarity(None, 200) == 0.5


def test_variant_penalty():
    assert scoring.variant_penalty("Creep", "Creep (Live)") < 0.5
    assert scoring.variant_penalty("Creep", "Creep (Acoustic)") < 0.5
    assert scoring.variant_penalty("Creep", "Creep - Sped Up") < 0.5
    assert scoring.variant_penalty("Creep", "Creep (Karaoke Version)") < 0.5
    assert scoring.variant_penalty("Creep (live)", "Creep (Live at Glastonbury)") == 1.0
    assert scoring.variant_penalty("Creep", "Creep - Remastered 2009") == 1.0
    # word inside a real title must not trigger
    assert scoring.variant_penalty("Live Forever", "Live Forever") == 1.0


def _q(n=12):
    return MBAlbumQuery(title="OK Computer", artist="Radiohead", year="1997", track_count=n, primary_type="Album")


def test_album_scoring_prefers_official(fixture):
    results = fixture("ytm_search_albums_ok_computer.json")
    q = _q()
    scored = sorted(
        ((scoring.score_album(q, r["title"], [a["name"] for a in r.get("artists", [])], r.get("year"), r.get("type")), r)
         for r in results if r.get("browseId")),
        key=lambda p: -p[0],
    )
    assert scored[0][1]["browseId"] == "MPREb_yXhSI4FCUo6"
    assert scored[0][0] > 0.8
    others = [s for s, r in scored if r.get("artists") and r["artists"][0]["name"] != "Radiohead"]
    assert all(s < 0.6 for s in others)


def test_album_score_track_count():
    q = _q()
    assert scoring.score_album(q, "OK Computer", ["Radiohead"], "1997", "Album", 12) > \
        scoring.score_album(q, "OK Computer", ["Radiohead"], "1997", "Album", 23)


def test_album_track_mapping_full(fixture):
    release = fixture("release_ok_computer.json")
    q = album_query_from_release(release)
    album = fixture("ytm_album_ok_computer.json")
    playlist = fixture("ytm_playlist_ok_computer.json")
    yt_tracks = scoring.album_tracks_from_ytm(album, "MPREb_yXhSI4FCUo6", playlist)
    # music-video entries replaced by art tracks from the audio playlist
    assert all(t.video_type == scoring.ATV for t in yt_tracks)
    mapping = scoring.map_album_tracks(q.tracks, yt_tracks, 1.0)
    assert len(mapping) == 12
    for t in q.tracks:
        best = mapping[t.track_id][0]
        assert best.score >= 0.9, (t.title, best)
        assert best.candidate.track_number == t.index
    ids = [mapping[t.track_id][0].candidate.video_id for t in q.tracks]
    assert len(set(ids)) == 12


def test_mapping_is_one_to_one_and_position_breaks_ties():
    tracks = [MBTrackQuery("a", "Intro", "X", 60_000, index=1), MBTrackQuery("b", "Intro", "X", 60_000, index=5)]
    yt = [YTCandidate("v1", "Intro", ["X"], duration=60, track_number=1, source="album"),
          YTCandidate("v5", "Intro", ["X"], duration=60, track_number=5, source="album")]
    m = scoring.map_album_tracks(tracks, yt, 1.0)
    assert m["a"][0].candidate.video_id == "v1"
    assert m["b"][0].candidate.video_id == "v5"


def test_composite_track_for_hidden_track():
    t = MBTrackQuery("t12", "Something in the Way / Endless, Nameless", "Nirvana", 1_235_160, index=12)
    yt = [YTCandidate("x11", "On A Plain", ["Nirvana"], duration=196, track_number=11, source="album"),
          YTCandidate("x12", "Something In The Way", ["Nirvana"], duration=232, track_number=12, source="album"),
          YTCandidate("x13", "Endless, Nameless", ["Nirvana"], duration=403, track_number=13, source="album")]
    m = scoring.map_album_tracks([t], yt, 1.0)
    best = m["t12"][0]
    assert best.candidate.video_id == "x12+x13"
    assert best.score >= 0.8


def test_song_ranking_prefers_art_track_and_penalizes_variants():
    t = MBTrackQuery("t", "Airbag", "Radiohead", 284_400)
    cands = [
        YTCandidate("live", "Airbag (Live)", ["Radiohead"], album="Live", duration=290, video_type=scoring.ATV),
        YTCandidate("omv", "Airbag", ["Radiohead"], album=None, duration=288, video_type="MUSIC_VIDEO_TYPE_OMV"),
        YTCandidate("atv", "Airbag", ["Radiohead"], album="OK Computer", duration=288, video_type=scoring.ATV),
        YTCandidate("cover", "Airbag", ["Some Cover Band"], album="Tribute to Radiohead", duration=280, video_type=scoring.ATV),
    ]
    ranked = scoring.rank_songs(t, "OK Computer", cands)
    assert ranked[0].candidate.video_id == "atv"
    by_id = {r.candidate.video_id: r.score for r in ranked}
    assert by_id["atv"] > by_id["omv"] > by_id["live"]
    assert by_id["cover"] < 0.7


def test_song_ranking_from_fixture(fixture):
    results = fixture("ytm_search_songs_airbag.json")
    cands = [c for r in results if (c := scoring.candidate_from_ytm(r, source="song"))]
    t = MBTrackQuery("t", "Airbag", "Radiohead", 284_400)
    ranked = scoring.rank_songs(t, "OK Computer", cands)
    assert ranked[0].candidate.title == "Airbag"
    assert ranked[0].score >= 0.85


def test_merge_candidates_dedupes_and_limits():
    a = [scoring.ScoredCandidate(YTCandidate(f"v{i}", "t", ["a"]), 0.1 * i) for i in range(5)]
    b = [scoring.ScoredCandidate(YTCandidate("v1", "t", ["a"]), 0.95)]
    merged = scoring.merge_candidates(a, b, limit=3)
    assert [m.candidate.video_id for m in merged] == ["v1", "v4", "v3"]
    assert merged[0].score == 0.95
