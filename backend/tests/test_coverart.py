import httpx
import pytest

from ofy import coverart

JPEG = b"\xff\xd8jpeg"


def _setup(monkeypatch, tmp_path, handler):
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr(coverart.env.__class__, "cover_cache_dir", property(lambda self: tmp_path))
    monkeypatch.setattr(coverart, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(coverart, "_limiter", coverart.RateLimiter(0))
    monkeypatch.setattr(coverart, "_sleep", fake_sleep)
    return sleeps


def scripted(responses: dict[str, list[int]], calls: list[str]):
    """Each URL suffix answers with its listed status codes in turn (the last one repeats)."""
    def handler(req: httpx.Request) -> httpx.Response:
        suffix = req.url.path.rsplit("/", 1)[1]
        calls.append(suffix)
        codes = responses.get(suffix, [404])
        code = codes.pop(0) if len(codes) > 1 else codes[0]
        return httpx.Response(code, content=JPEG if code == 200 else b"")
    return handler


async def test_server_error_is_retried_with_backoff(tmp_path, monkeypatch):
    calls = []
    sleeps = _setup(monkeypatch, tmp_path, scripted({"front-1200": [500, 502, 200]}, calls))
    assert await coverart.fetch_front("release", "r1", "1200") == JPEG
    assert calls == ["front-1200"] * 3
    assert sleeps == [0.5, 1.0]
    assert (tmp_path / "release-r1-1200.jpg").read_bytes() == JPEG


async def test_falls_back_to_next_best_variant_after_retries(tmp_path, monkeypatch):
    calls = []
    sleeps = _setup(monkeypatch, tmp_path, scripted({"front-1200": [500], "front": [200]}, calls))
    assert await coverart.fetch_front("release", "r1", "1200") == JPEG
    assert calls == ["front-1200"] * 3 + ["front"]
    assert len(sleeps) == 2
    assert (tmp_path / "release-r1-1200.jpg").is_file()  # the original is at least as good: cached


async def test_missing_variant_is_not_retried(tmp_path, monkeypatch):
    calls = []
    sleeps = _setup(monkeypatch, tmp_path, scripted({"front-1200": [404], "front": [200]}, calls))
    assert await coverart.fetch_front("release", "r1", "1200") == JPEG
    assert calls == ["front-1200", "front"]
    assert sleeps == []


async def test_smaller_variant_is_served_but_not_cached(tmp_path, monkeypatch):
    calls = []
    _setup(monkeypatch, tmp_path, scripted({"front-500": [500], "front-1200": [500], "front-250": [200]}, calls))
    assert await coverart.fetch_front("release", "r1", "500") == JPEG
    assert calls == ["front-500"] * 3 + ["front-1200"] * 3 + ["front-250"]
    assert not (tmp_path / "release-r1-500.jpg").exists()


async def test_no_cover_is_negative_cached(tmp_path, monkeypatch):
    calls = []
    _setup(monkeypatch, tmp_path, scripted({}, calls))
    assert await coverart.fetch_front("release", "r1", "250") is None
    assert calls == ["front-250", "front-500"]
    assert await coverart.fetch_front("release", "r1", "250") is None  # answered from cache
    assert len(calls) == 2


async def test_persistent_failure_raises_and_is_not_cached(tmp_path, monkeypatch):
    calls = []
    _setup(monkeypatch, tmp_path, scripted({"front-250": [500], "front-500": [404]}, calls))
    with pytest.raises(coverart.CoverUnavailable):
        await coverart.fetch_front("release", "r1", "250")
    assert calls == ["front-250"] * 3 + ["front-500"]
    assert list(tmp_path.iterdir()) == []


async def test_network_errors_are_retried(tmp_path, monkeypatch):
    attempts = []

    def handler(req):
        attempts.append(1)
        if len(attempts) < 3:
            raise httpx.ConnectError("boom")
        return httpx.Response(200, content=JPEG)

    _setup(monkeypatch, tmp_path, handler)
    assert await coverart.fetch_front("release", "r1", "250") == JPEG
    assert len(attempts) == 3


async def test_429_honours_retry_after(tmp_path, monkeypatch):
    calls = []

    def handler(req):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={"retry-after": "4"})
        return httpx.Response(200, content=JPEG)

    sleeps = _setup(monkeypatch, tmp_path, handler)
    assert await coverart.fetch_front("release", "r1", "250") == JPEG
    assert sleeps == [4.0]


async def test_front_for_release_falls_back_to_release_group_when_unavailable(tmp_path, monkeypatch):
    def handler(req):
        if "/release/" in req.url.path:
            return httpx.Response(500)
        return httpx.Response(200, content=JPEG)

    _setup(monkeypatch, tmp_path, handler)
    assert await coverart.front_for_release("r1", "rg1", "1200") == JPEG
