import json

import pytest
from sqlmodel import select

from ofy import ytimport
from ofy.db import Job, Track, YTImport, session
from ofy.jobs import queue
from ofy.match.scoring import ATV

AIRBAG_REC = "4a7fea2e-545b-4c63-bc9a-9943cc3a29d7"
AIRBAG_TRACK = "ff7733a6-6903-3e2e-b683-6dbbb0f59ec6"
OK_COMPUTER = "1834eae1-741b-3c03-9ca5-0df3decb43ea"


@pytest.mark.parametrize("url, kind, id", [
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "video", "dQw4w9WgXcQ"),
    ("https://music.youtube.com/watch?v=dQw4w9WgXcQ&list=OLAK5uy_abc", "video", "dQw4w9WgXcQ"),
    ("youtu.be/dQw4w9WgXcQ?t=42", "video", "dQw4w9WgXcQ"),
    ("https://m.youtube.com/shorts/dQw4w9WgXcQ", "video", "dQw4w9WgXcQ"),
    ("dQw4w9WgXcQ", "video", "dQw4w9WgXcQ"),
    ("https://www.youtube.com/playlist?list=PLx0sYbCqOb8TBPRdmBHs5Iftvv9TPboYG", "playlist",
     "PLx0sYbCqOb8TBPRdmBHs5Iftvv9TPboYG"),
    ("https://music.youtube.com/browse/VLPLabc", "playlist", "PLabc"),
    ("https://music.youtube.com/browse/MPREb_lBLylZFCj1l", "album", "MPREb_lBLylZFCj1l"),
])
def test_parse_link(url, kind, id):
    assert ytimport.parse_link(url) == ytimport.Link(kind, id)


@pytest.mark.parametrize("url", ["https://vimeo.com/123", "https://www.youtube.com/@channel", "watch?v=short"])
def test_parse_link_rejects(url):
    with pytest.raises(ValueError):
        ytimport.parse_link(url)


def test_query_variants():
    # an upload by some channel: "Artist - Title" first, the channel as artist last resort
    assert ytimport.query_variants("Pink Floyd - Comfortably Numb (Official Video) [HD]", ["SomeFan"], "MUSIC_VIDEO_TYPE_UGC") == [
        ("Comfortably Numb", ("Pink Floyd",)),
        ("Pink Floyd - Comfortably Numb", ("SomeFan",)),
        ("Pink Floyd", ("Comfortably Numb",)),
    ]
    # official audio already has the music metadata
    assert ytimport.query_variants("Time", ["Pink Floyd - Topic"], ATV) == [("Time", ("Pink Floyd",))]


def _hit(rec_id, title, length, release, artist="Radiohead", disambiguation=None):
    return {"id": rec_id, "title": title, "length": length, "disambiguation": disambiguation,
            "artist-credit": [{"name": artist, "artist": {"id": "a", "name": artist}}], "releases": [release]}


_STUDIO = {"id": OK_COMPUTER, "title": "OK Computer", "status": "Official", "date": "1997-05-21",
           "release-group": {"id": "rg", "primary-type": "Album", "secondary-types": []}, "media": [{"format": "CD"}]}
_LIVE = {"id": "live-rel", "title": "Live in Paris", "status": "Official", "date": "2001",
         "release-group": {"id": "rg2", "primary-type": "Album", "secondary-types": ["Live"]}, "media": []}


class FakeMB:
    def __init__(self, fixture, hits):
        self.release_json = fixture("release_ok_computer.json")
        self.hits = hits
        self.queries = []

    async def search(self, entity, query, limit=25, offset=0):
        self.queries.append(query)
        return {"recordings": self.hits}

    async def release(self, mbid, fresh=False):
        assert mbid == OK_COMPUTER
        return self.release_json

    async def recording(self, mbid):
        return {"id": mbid, "releases": [_STUDIO]}


class FakeYTM:
    def __init__(self, tracks=None, playlist=None):
        self.tracks = tracks or {}
        self.playlist = playlist

    async def get_track(self, video_id):
        return self.tracks.get(video_id)

    async def get_full_playlist(self, playlist_id):
        return self.playlist


@pytest.fixture
def fakes(tmp_db, fixture, monkeypatch):
    def install(hits, **ytm):
        mb, yt = FakeMB(fixture, hits), FakeYTM(**ytm)
        monkeypatch.setattr(ytimport, "get_mb", lambda: mb)
        monkeypatch.setattr(ytimport, "get_ytm", lambda: yt)
        return mb, yt
    return install


AIRBAG_VIDEO = {"videoId": "airbagVideo", "title": "Airbag", "artists": [{"name": "Radiohead"}],
                "album": {"name": "OK Computer"}, "length": "4:44", "videoType": ATV}


async def _resolve_all():
    with session() as s:
        jobs = list(s.exec(select(Job).where(Job.kind == ytimport.JOB_KIND, Job.status == "pending")).all())
    for j in jobs:
        await ytimport.handle_resolve(j)


def _imports():
    with session() as s:
        return list(s.exec(select(YTImport).order_by(YTImport.position)).all())


async def test_video_is_downloaded_as_its_musicbrainz_track(fakes):
    mb, _ = fakes([_hit("live-rec", "Airbag", 300000, _LIVE, disambiguation="live"),
                   _hit(AIRBAG_REC, "Airbag", 284400, _STUDIO)],
                  tracks={"airbagVideo": AIRBAG_VIDEO})
    out = await ytimport.start_import("https://music.youtube.com/watch?v=airbagVideo")
    assert out["queued"] == 1 and out["kind"] == "video"
    await _resolve_all()
    imp, = _imports()
    assert imp.status == "matched" and imp.track_id == AIRBAG_TRACK and imp.title == "Airbag"
    with session() as s:
        t = s.get(Track, AIRBAG_TRACK)
        job = s.exec(select(Job).where(Job.kind == "download", Job.track_id == AIRBAG_TRACK)).one()
    # the pasted video is the audio, MusicBrainz the metadata (the track row comes from the release)
    assert (t.status, t.video_id, t.match_source, t.title, t.artist) == ("queued", "airbagVideo", "manual", "Airbag", "Radiohead")
    assert job.release_id == OK_COMPUTER
    assert 'recording:"Airbag"' in mb.queries[0] and "status:official" in mb.queries[0]


async def test_unsure_match_waits_for_a_choice(fakes):
    fakes([_hit(AIRBAG_REC, "Airbag", 284400, _STUDIO)],
          tracks={"otherVideoX": {**AIRBAG_VIDEO, "videoId": "otherVideoX", "title": "Paranoid Android",
                                  "artists": [{"name": "Some Cover Band"}]}})
    await ytimport.start_import("otherVideoX")
    await _resolve_all()
    imp, = _imports()
    assert imp.status == "needs_review" and imp.track_id is None
    assert [c["recording_id"] for c in json.loads(imp.candidates)] == [AIRBAG_REC]
    assert not queue_has_download()

    imp = await ytimport.choose_recording(imp.id, AIRBAG_REC, None)  # release picked for it
    assert imp.status == "matched" and imp.track_id == AIRBAG_TRACK
    assert queue_has_download()


def queue_has_download():
    with session() as s:
        return s.exec(select(Job).where(Job.kind == "download")).first() is not None


async def test_playlist_imports_every_video_once(fakes):
    entries = [{**AIRBAG_VIDEO, "videoId": f"video{i:06d}", "duration_seconds": 284} for i in range(3)]
    fakes([_hit(AIRBAG_REC, "Airbag", 284400, _STUDIO)],
          playlist={"title": "Mix", "tracks": entries + [{"videoId": None, "title": "deleted"}]})
    out = await ytimport.start_import("https://www.youtube.com/playlist?list=PLmix")
    assert (out["kind"], out["queued"], out["title"]) == ("playlist", 3, "Mix")
    assert [(i.batch, i.title, i.duration) for i in _imports()] == [("PLmix", "Airbag", 284)] * 3
    again = await ytimport.start_import("https://www.youtube.com/playlist?list=PLmix")
    assert again["queued"] == 0 and len(_imports()) == 3


async def test_song_already_downloaded_is_not_downloaded_again(fakes):
    fakes([_hit(AIRBAG_REC, "Airbag", 284400, _STUDIO)], tracks={"airbagVideo": AIRBAG_VIDEO})
    from ofy.tracks import ensure_release_rows, update_track

    ensure_release_rows(ytimport.get_mb().release_json)
    update_track(AIRBAG_TRACK, status="done", video_id="theOriginal")
    await ytimport.start_import("airbagVideo")
    await _resolve_all()
    imp, = _imports()
    assert imp.status == "in_library" and imp.track_id == AIRBAG_TRACK
    with session() as s:
        assert s.get(Track, AIRBAG_TRACK).video_id == "theOriginal"
    assert not queue_has_download()
    assert ytimport.clear_finished() == 1 and _imports() == []


def test_resolve_jobs_are_not_listed_as_downloads(tmp_db):
    from ofy.api.actions import downloads

    queue.enqueue(ytimport.JOB_KIND, track_id="yt:1")
    assert downloads() == {"active": [], "recent": []}


def _va(release_id, title):
    return {"id": release_id, "title": title, "status": "Official", "date": "1982",
            "artist-credit": [{"name": "Various Artists", "artist": {"id": "89ad4ac3-39f7-470e-963a-56509c546377"}}],
            "release-group": {"id": f"rg-{release_id}", "primary-type": "Album", "secondary-types": ["Compilation"]}}


def test_artist_album_recording_beats_a_compilation_copy_closer_in_length():
    # A music video of 234s: one various-artists compilation has its own copy of the hit at 236s;
    # the recording on the artist's album (and on many more releases) is 250s long.
    imp = YTImport(video_id="v", batch="v", title="Angel Of The Morning (Official Music Video)",
                   artists='["Juice Newton"]', duration=234, video_type="MUSIC_VIDEO_TYPE_OMV")
    album = {**_STUDIO, "id": "juice", "title": "Juice"}
    copy = ytimport.score_recording(_hit("copy", "Angel Of The Morning", 236000, _va("night", "Night Flight"),
                                         artist="Juice Newton"), "Angel Of The Morning", ("Juice Newton",), imp, set())
    original = _hit("orig", "Angel of the Morning", 250120, album, artist="Juice Newton")
    original["releases"] += [_va(f"va{i}", f"Hits {i}") for i in range(30)]
    best = ytimport.score_recording(original, "Angel Of The Morning", ("Juice Newton",), imp, set())
    assert best.score > copy.score and best.score >= ytimport.ACCEPT
    assert best.release_id == "juice"  # filed under the artist's album, not one of the compilations


def test_pick_release_prefers_the_artists_own_release():
    single = {**_STUDIO, "id": "single", "title": "Angel of the Morning",
              "release-group": {"id": "rg-s", "primary-type": "Single", "secondary-types": []}}
    assert ytimport.pick_release([_va("night", "Night Flight"), single], None, set())["id"] == "single"
    assert ytimport.pick_release([_va("night", "Night Flight")], None, set())["id"] == "night"  # if that's all there is
