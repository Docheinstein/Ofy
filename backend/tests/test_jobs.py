import asyncio

import pytest
from sqlmodel import select

from offliner import jobs as jobs_mod
from offliner.db import Job, Track, recover_interrupted_jobs, session
from offliner.jobs import JobQueue, PermanentError


@pytest.fixture
def q(tmp_db, monkeypatch):
    monkeypatch.setattr(jobs_mod, "backoff_delay", lambda attempt: 0.0)
    queue = JobQueue()
    yield queue


async def drain(queue: JobQueue, timeout=5.0):
    queue.start()
    t0 = asyncio.get_running_loop().time()
    while asyncio.get_running_loop().time() - t0 < timeout:
        with session() as s:
            if not s.exec(select(Job).where(Job.status.in_(["pending", "running"]))).first():  # type: ignore[attr-defined]
                break
        await asyncio.sleep(0.05)
    await queue.stop()


async def test_runs_and_completes(q):
    seen = []

    async def handler(job):
        seen.append(job.track_id)

    q.register("download", handler)
    q.enqueue("download", track_id="a")
    q.enqueue("download", track_id="b")
    await drain(q)
    assert sorted(seen) == ["a", "b"]
    with session() as s:
        assert {j.status for j in s.exec(select(Job)).all()} == {"done"}


async def test_dedupes_pending(q):
    j1 = q.enqueue("download", track_id="a")
    j2 = q.enqueue("download", track_id="a")
    assert j1.id == j2.id


async def test_retries_then_succeeds(q):
    calls = []

    async def flaky(job):
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("boom")

    q.register("download", flaky)
    q.enqueue("download", track_id="a")
    await drain(q)
    with session() as s:
        j = s.exec(select(Job)).one()
    assert len(calls) == 3 and j.status == "done" and j.attempts == 2


async def test_gives_up_after_max_retries_and_calls_hook(q):
    failed = []

    async def bad(job):
        raise RuntimeError("nope")

    async def hook(job, err):
        failed.append((job.status, err))

    q.register("download", bad, hook)
    q.enqueue("download", track_id="a")
    await drain(q)
    with session() as s:
        j = s.exec(select(Job)).one()
    assert j.status == "failed" and j.attempts == 4  # default max_retries=3 -> 1 + 3 attempts
    assert failed[-1][0] == "failed" and "nope" in failed[-1][1]


async def test_permanent_error_no_retry(q):
    async def bad(job):
        raise PermanentError("gone")

    q.register("download", bad)
    q.enqueue("download", track_id="a")
    await drain(q)
    with session() as s:
        j = s.exec(select(Job)).one()
    assert j.status == "failed" and j.attempts == 1


async def test_concurrency_limit(q):
    running = 0
    peak = 0

    async def slow(job):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.1)
        running -= 1

    q.register("download", slow)
    for i in range(6):
        q.enqueue("download", track_id=str(i))
    await drain(q)
    assert peak == 2  # default concurrency


def test_recover_interrupted(tmp_db):
    with session() as s:
        s.add(Job(kind="download", track_id="a", status="running"))
        s.add(Track(track_id="a", recording_id="r", release_id="rel", release_group_id="rg", status="downloading"))
        s.commit()
    assert recover_interrupted_jobs() == 1
    with session() as s:
        assert s.exec(select(Job)).one().status == "pending"
        assert s.get(Track, "a").status == "queued"
