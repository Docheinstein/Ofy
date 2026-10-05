from offliner.mb import logic


def test_artist_credit_string_with_join_phrases():
    credits = [
        {"name": "Daft Punk", "joinphrase": " feat. ", "artist": {"id": "a", "name": "Daft Punk", "sort-name": "Daft Punk"}},
        {"name": "Romanthony", "joinphrase": "", "artist": {"id": "b", "name": "Romanthony", "sort-name": "Romanthony"}},
    ]
    assert logic.artist_credit_string(credits) == "Daft Punk feat. Romanthony"
    assert logic.artist_credit_names(credits) == ["Daft Punk", "Romanthony"]
    assert logic.artist_credit_ids(credits) == ["a", "b"]
    assert logic.artist_credit_sort(credits) == "Daft Punk feat. Romanthony"


def test_discography_buckets(fixture):
    data = fixture("rgs_radiohead.json")
    groups = logic.group_discography(data["release-groups"])
    names = [g["type"] for g in groups]
    assert names[0] == "Album"
    assert set(names) <= set(logic.DISCOGRAPHY_ORDER)
    albums = {i["title"] for i in groups[0]["items"]}
    assert "OK Computer" in albums
    # newest first
    dates = [i["first_release_date"] or "" for i in groups[0]["items"]]
    assert dates == sorted(dates, reverse=True)


def test_bucket_rules():
    assert logic.discography_bucket({"primary-type": "Album", "secondary-types": ["Live"]}) == "Live"
    assert logic.discography_bucket({"primary-type": "Album", "secondary-types": ["Compilation"]}) == "Compilation"
    assert logic.discography_bucket({"primary-type": "EP", "secondary-types": []}) == "Single/EP"
    assert logic.discography_bucket({"primary-type": "Single"}) == "Single/EP"
    assert logic.discography_bucket({"primary-type": "Album", "secondary-types": ["Soundtrack"]}) == "Other"
    assert logic.discography_bucket({"primary-type": "Broadcast"}) == "Other"


def test_related_artists(fixture):
    rel = logic.related_artists(fixture("artist_radiohead.json"))
    names = {r["name"] for r in rel}
    assert "Thom Yorke" in names
    assert len({r["id"] for r in rel}) == len(rel)


def test_canonical_release_prefers_official_cd_earliest():
    releases = [
        {"id": "vinyl", "status": "Official", "date": "1997-05-01", "media": [{"format": '12" Vinyl'}]},
        {"id": "boot", "status": "Bootleg", "date": "1990", "media": [{"format": "CD"}]},
        {"id": "cd-late", "status": "Official", "date": "2009-03-24", "media": [{"format": "CD"}]},
        {"id": "cd-early", "status": "Official", "date": "1997-05-21", "media": [{"format": "CD"}]},
        {"id": "digital", "status": "Official", "date": "2016-01-01", "media": [{"format": "Digital Media"}]},
    ]
    assert logic.pick_canonical_release(releases)["id"] == "cd-early"


def test_canonical_release_precise_date_beats_year_only():
    releases = [
        {"id": "year", "status": "Official", "date": "1997", "media": [{"format": "CD"}]},
        {"id": "full", "status": "Official", "date": "1997-05-21", "media": [{"format": "CD"}]},
    ]
    assert logic.pick_canonical_release(releases)["id"] == "full"


def test_canonical_release_country_tiebreak():
    releases = [
        {"id": "a-jp", "status": "Official", "date": "1997-05-21", "country": "JP", "media": [{"format": "CD"}]},
        {"id": "z-gb", "status": "Official", "date": "1997-05-21", "country": "GB", "media": [{"format": "CD"}]},
    ]
    assert logic.pick_canonical_release(releases)["id"] == "z-gb"


def test_canonical_ok_computer_has_12_tracks(fixture):
    data = fixture("releases_ok_computer.json")
    best = logic.pick_canonical_release(data["releases"])
    assert best["status"] == "Official"
    assert logic.release_track_count(best) == 12


def test_tracklist(fixture):
    rows = logic.tracklist(fixture("release_ok_computer.json"))
    assert len(rows) == 12
    assert rows[0]["title"] == "Airbag"
    assert rows[0]["disc"] == 1 and rows[0]["position"] == 1 and rows[0]["track_total"] == 12
    assert all(r["length_ms"] for r in rows)
    assert rows[-1]["position"] == 12
