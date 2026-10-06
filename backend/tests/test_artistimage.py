import httpx

from ofy import artistimage


def _claim(value, rank="normal"):
    return {"rank": rank, "mainsnak": {"datavalue": {"value": value}}}


def test_parse_search_qid():
    assert artistimage.parse_search_qid({"query": {"search": [{"title": "Q2306"}]}}) == "Q2306"
    assert artistimage.parse_search_qid({"query": {"search": []}}) is None
    assert artistimage.parse_search_qid({}) is None


def test_parse_image_prefers_preferred_rank_and_skips_deprecated():
    data = {"claims": {"P18": [_claim("old.jpg", "deprecated"), _claim("normal.jpg"), _claim("best.jpg", "preferred")]}}
    assert artistimage.parse_image_filename(data) == "best.jpg"
    assert artistimage.parse_image_filename({"claims": {"P18": [_claim("x.jpg", "deprecated")]}}) is None
    assert artistimage.parse_image_filename({"claims": {}}) is None


def test_wikidata_id_from_musicbrainz_artist(fixture):
    assert artistimage.wikidata_id_from_artist(fixture("artist_radiohead.json")) == "Q44190"
    assert artistimage.wikidata_id_from_artist({"relations": []}) is None


def test_commons_thumb_url():
    url = artistimage.commons_thumb_url("Pink Floyd, 1971 (HQ).jpg", 500)
    assert url == "https://commons.wikimedia.org/wiki/Special:FilePath/Pink_Floyd%2C_1971_%28HQ%29.jpg?width=500"


def test_retry_after():
    assert artistimage.retry_after_seconds(httpx.Response(429, headers={"retry-after": "3"})) == 3
    assert artistimage.retry_after_seconds(httpx.Response(429, headers={"retry-after": "999"}), cap=600) == 600
    assert artistimage.retry_after_seconds(httpx.Response(429), default=30, cap=600) == 30


def _setup(monkeypatch, tmp_path, handler):
    monkeypatch.setattr(artistimage.env.__class__, "cover_cache_dir", property(lambda self: tmp_path))
    monkeypatch.setattr(artistimage, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(artistimage, "_limiter", artistimage.RateLimiter(0))


def wikidata_handler(calls):
    def handler(req: httpx.Request) -> httpx.Response:
        action = req.url.params.get("action")
        calls.append(action or req.url.host)
        if action == "query":
            return httpx.Response(200, json={"query": {"search": [{"title": "Q1"}]}})
        if action == "wbgetclaims":
            return httpx.Response(200, json={"claims": {"P18": [_claim("A.jpg")]}})
        return httpx.Response(200, content=b"\xff\xd8jpeg", headers={"content-type": "image/jpeg"})
    return handler


async def test_lookup_cached_per_artist_not_per_size(tmp_db, tmp_path, monkeypatch):
    calls = []
    _setup(monkeypatch, tmp_path, wikidata_handler(calls))
    assert await artistimage.fetch_artist_image("m1", "500") == b"\xff\xd8jpeg"
    assert await artistimage.fetch_artist_image("m1", "250") == b"\xff\xd8jpeg"
    assert await artistimage.fetch_artist_image("m1", "250") == b"\xff\xd8jpeg"  # disk cache
    assert calls == ["query", "wbgetclaims", "commons.wikimedia.org", "commons.wikimedia.org"]


async def test_known_qid_skips_search(tmp_db, tmp_path, monkeypatch):
    calls = []
    _setup(monkeypatch, tmp_path, wikidata_handler(calls))
    assert await artistimage.fetch_artist_image("m3", "500", qid="Q1")
    assert calls == ["wbgetclaims", "commons.wikimedia.org"]


async def test_missing_photo_is_cached(tmp_db, tmp_path, monkeypatch):
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(200, json={"query": {"search": []}})

    _setup(monkeypatch, tmp_path, handler)
    assert await artistimage.fetch_artist_image("m2") is None
    assert await artistimage.fetch_artist_image("m2") is None  # answered from cache
    assert len(calls) == 1


async def test_429_pauses_all_lookups_and_is_not_cached(tmp_db, tmp_path, monkeypatch):
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(429, headers={"retry-after": "20"})

    _setup(monkeypatch, tmp_path, handler)
    monkeypatch.setattr(artistimage, "_cooldown_until", 0.0)
    assert await artistimage.fetch_artist_image("a") is None
    assert await artistimage.fetch_artist_image("b") is None  # skipped during cooldown
    assert len(calls) == 1
    monkeypatch.setattr(artistimage, "_cooldown_until", 0.0)  # cooldown over
    assert await artistimage.fetch_artist_image("a") is None
    assert len(calls) == 2  # "a" was not negative-cached



async def test_prefetch_warms_cache_only(monkeypatch, tmp_path):
    calls = []

    async def fake_fetch(mbid, size="500", qid=None):
        calls.append((mbid, size))
        return b"jpeg"

    monkeypatch.setattr(artistimage, "fetch_artist_image", fake_fetch)
    await artistimage.prefetch_artist_image("pf-id")
    # Various Artists and unknown artists have no photo to fetch
    from ofy.tagging.model import VARIOUS_ARTISTS_ID
    await artistimage.prefetch_artist_image(VARIOUS_ARTISTS_ID)
    await artistimage.prefetch_artist_image(None)
    assert calls == [("pf-id", "250")]
