"""Persistent job queue backed by the SQLite `job` table.

Jobs survive restarts (running jobs are reset to pending on startup), run with a
configurable concurrency and are retried with exponential backoff + jitter.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable

from sqlmodel import col, select

from offliner.db import Job, load_settings, session

log = logging.getLogger(__name__)

Handler = Callable[[Job], Awaitable[None]]
FailHook = Callable[[Job, str], Awaitable[None] | None]


class PermanentError(Exception):
    """Raise from a handler to fail a job without retrying."""


def backoff_delay(attempt: int, base: float = 10.0, cap: float = 600.0) -> float:
    return min(cap, base * (2 ** max(0, attempt - 1))) + random.uniform(0, base / 2)


class JobQueue:
    def __init__(self) -> None:
        self.handlers: dict[str, Handler] = {}
        self.fail_hooks: dict[str, FailHook] = {}
        self._wake = asyncio.Event()
        self._running: dict[int, asyncio.Task] = {}
        self._loop_task: asyncio.Task | None = None
        self._stopping = False

    def register(self, kind: str, handler: Handler, on_failed: FailHook | None = None) -> None:
        self.handlers[kind] = handler
        if on_failed:
            self.fail_hooks[kind] = on_failed

    def wake(self) -> None:
        try:
            self._wake.set()
        except RuntimeError:
            pass

    def enqueue(self, kind: str, *, track_id: str | None = None, release_id: str | None = None,
                dedupe: bool = True) -> Job:
        with session() as s:
            if dedupe:
                existing = s.exec(
                    select(Job).where(
                        Job.kind == kind,
                        Job.track_id == track_id,
                        Job.release_id == release_id,
                        col(Job.status).in_(["pending", "running"]),
                    )
                ).first()
                if existing:
                    return existing
            job = Job(kind=kind, track_id=track_id, release_id=release_id)
            s.add(job)
            s.commit()
            s.refresh(job)
        self.wake()
        return job

    def cancel_for_track(self, track_id: str) -> int:
        with session() as s:
            jobs = s.exec(select(Job).where(Job.track_id == track_id, Job.status == "pending")).all()
            for j in jobs:
                j.status = "failed"
                j.error = "cancelled"
                s.add(j)
            s.commit()
            return len(jobs)

    def start(self) -> None:
        if self._loop_task is None:
            self._stopping = False
            self._loop_task = asyncio.create_task(self._dispatch_loop(), name="job-dispatcher")

    async def stop(self) -> None:
        self._stopping = True
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except (asyncio.CancelledError, Exception):
                pass
            self._loop_task = None
        for t in list(self._running.values()):
            t.cancel()
        self._running.clear()

    def _next_job(self, exclude: set[int]) -> Job | None:
        now = time.time()
        with session() as s:
            q = (
                select(Job)
                .where(Job.status == "pending", Job.next_run_at <= now)
                .order_by(col(Job.created_at), col(Job.id))
                .limit(len(exclude) + 1)
            )
            for job in s.exec(q).all():
                if job.id not in exclude:
                    job.status = "running"
                    job.updated_at = now
                    s.add(job)
                    s.commit()
                    s.refresh(job)
                    return job
        return None

    def _next_due_in(self) -> float:
        with session() as s:
            job = s.exec(
                select(Job).where(Job.status == "pending").order_by(col(Job.next_run_at)).limit(1)
            ).first()
        if job is None:
            return 30.0
        return max(0.2, min(30.0, job.next_run_at - time.time()))

    async def _dispatch_loop(self) -> None:
        while not self._stopping:
            try:
                concurrency = load_settings().concurrency
                while len(self._running) < concurrency:
                    job = self._next_job(set(self._running))
                    if job is None:
                        break
                    task = asyncio.create_task(self._run(job), name=f"job-{job.id}")
                    self._running[job.id] = task  # type: ignore[index]
                self._wake.clear()
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=self._next_due_in())
                except TimeoutError:
                    pass
            except asyncio.CancelledError:
                raise
            except Exception:  # pragma: no cover - defensive
                log.exception("dispatcher error")
                await asyncio.sleep(2)

    async def _run(self, job: Job) -> None:
        handler = self.handlers.get(job.kind)
        error: str | None = None
        permanent = False
        try:
            if handler is None:
                raise PermanentError(f"no handler for job kind {job.kind}")
            await handler(job)
        except asyncio.CancelledError:
            with session() as s:
                j = s.get(Job, job.id)
                if j and j.status == "running":
                    j.status = "pending"
                    s.add(j)
                    s.commit()
            raise
        except PermanentError as e:
            error, permanent = str(e) or e.__class__.__name__, True
        except Exception as e:
            log.exception("job %s (%s) failed", job.id, job.kind)
            error = f"{e.__class__.__name__}: {e}"
        finally:
            self._running.pop(job.id, None)  # type: ignore[arg-type]
            self.wake()

        with session() as s:
            j = s.get(Job, job.id)
            if j is None:
                return
            j.updated_at = time.time()
            if error is None:
                j.status = "done"
                j.error = None
            else:
                j.attempts += 1
                j.error = error[:1000]
                max_retries = load_settings().max_retries
                if permanent or j.attempts > max_retries:
                    j.status = "failed"
                else:
                    j.status = "pending"
                    j.next_run_at = time.time() + backoff_delay(j.attempts)
            s.add(j)
            s.commit()
            s.refresh(j)
        if error is not None:
            hook = self.fail_hooks.get(job.kind)
            if hook:
                res = hook(j, error if j.status == "failed" else "")
                if asyncio.iscoroutine(res):
                    await res


queue = JobQueue()
