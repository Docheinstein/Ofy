from ofy.db import Track, session
from ofy.match.engine import TrackMatch
from ofy.match.scoring import ScoredCandidate, YTCandidate
from ofy.pipeline import apply_match, candidates_of


def _track():
    with session() as s:
        s.add(Track(track_id="t", recording_id="r", release_id="rel", release_group_id="rg", status="queued"))
        s.commit()


def _m(score):
    c = ScoredCandidate(YTCandidate("vid", "Title", ["A"], source="song"), score)
    alt = ScoredCandidate(YTCandidate("alt", "Title (Live)", ["A"], source="song"), score / 2)
    return TrackMatch("t", c, "song", [c, alt])


def test_low_confidence_needs_review(tmp_db):
    _track()
    assert apply_match("t", _m(0.5), 0.7) is False
    with session() as s:
        t = s.get(Track, "t")
    assert t.status == "needs_review" and t.video_id == "vid" and t.match_score == 0.5
    assert [c["video_id"] for c in candidates_of("t")] == ["vid", "alt"]


def test_confident_match_stays_queued(tmp_db):
    _track()
    assert apply_match("t", _m(0.9), 0.7) is True
    with session() as s:
        t = s.get(Track, "t")
    assert t.status == "queued" and t.match_source == "song"


def test_no_match(tmp_db):
    _track()
    assert apply_match("t", TrackMatch("t", None, None, []), 0.7) is False
    with session() as s:
        t = s.get(Track, "t")
    assert t.status == "needs_review" and t.error
