"""Job queue with pluggable backend.

memory : asyncio queue inside one process (default)
redis  : shared Redis list — run any number of `python -m app.worker` processes on any
         number of machines; each pulls jobs with BLMOVE and claims them atomically in the DB.

A reaper re-queues jobs whose worker stopped heart-beating (crash, deploy, OOM), so
interrupted workflows resume from the last completed step.
"""
from __future__ import annotations

import asyncio
import logging
import os
import socket
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from ..config import settings
from ..database import SessionLocal
from ..models import Job, utcnow
from .runner import run_job

log = logging.getLogger("siteforge.queue")


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=timezone.utc) if dt and dt.tzinfo is None else dt


class JobQueue:
    QUEUE_KEY = "siteforge:jobs"
    PROCESSING_KEY = "siteforge:jobs:processing"

    def __init__(self) -> None:
        self.worker_id = f"{socket.gethostname()}:{os.getpid()}"
        self.backend = "redis" if settings.REDIS_URL else "memory"
        self._mem: asyncio.Queue[str] | None = None
        self._redis = None
        self._tasks: list[asyncio.Task] = []
        self.running: set[str] = set()
        self.workers = 0

    def _ensure(self) -> None:
        if self.backend == "redis" and self._redis is None:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        if self.backend == "memory" and self._mem is None:
            self._mem = asyncio.Queue()

    async def enqueue(self, job_id: str) -> None:
        self._ensure()
        if self.backend == "redis":
            await self._redis.lpush(self.QUEUE_KEY, job_id)
        else:
            await self._mem.put(job_id)

    async def size(self) -> int:
        self._ensure()
        if self.backend == "redis":
            return int(await self._redis.llen(self.QUEUE_KEY))
        return self._mem.qsize()

    async def _next(self) -> str | None:
        if self.backend == "redis":
            return await self._redis.blmove(self.QUEUE_KEY, self.PROCESSING_KEY, timeout=5, src="RIGHT", dest="LEFT")
        try:
            return await asyncio.wait_for(self._mem.get(), timeout=5)
        except asyncio.TimeoutError:
            return None

    async def _worker(self, n: int) -> None:
        while True:
            try:
                job_id = await self._next()
                if not job_id:
                    continue
                self.running.add(job_id)
                try:
                    await run_job(job_id, f"{self.worker_id}#{n}")
                finally:
                    self.running.discard(job_id)
                    if self.backend == "redis":
                        await self._redis.lrem(self.PROCESSING_KEY, 1, job_id)
            except asyncio.CancelledError:
                raise
            except Exception:  # keep the worker alive no matter what
                log.exception("Worker %s crashed while processing; continuing", n)
                await asyncio.sleep(1)

    async def _reaper(self) -> None:
        while True:
            try:
                await self.recover()
            except Exception:
                log.exception("Reaper failed")
            await asyncio.sleep(60)

    async def recover(self, startup: bool = False) -> int:
        """Re-queue queued jobs and stale running jobs. Returns how many were re-queued."""
        db = SessionLocal()
        count = 0
        try:
            cutoff = utcnow() - timedelta(seconds=settings.STALE_JOB_SECONDS)
            jobs = db.scalars(select(Job).where(Job.status.in_(("queued", "running")))).all()
            for job in jobs:
                stale = job.status == "running" and (_aware(job.heartbeat_at) or cutoff) <= cutoff and job.id not in self.running
                # on single-process startup every 'running' job is orphaned
                orphan = startup and self.backend == "memory" and job.status == "running"
                if job.status == "queued" and (startup or self.backend == "memory" and job.id not in self.running):
                    if startup:
                        await self.enqueue(job.id)
                        count += 1
                elif stale or orphan:
                    for s in job.steps:
                        if s.status in ("running", "retrying"):
                            s.status = "pending"
                    job.status = "queued"
                    db.commit()
                    await self.enqueue(job.id)
                    count += 1
                    log.warning("Resuming interrupted job %s", job.id)
        finally:
            db.close()
        return count

    async def start(self, concurrency: int) -> None:
        if self.backend == "memory":
            self._mem = asyncio.Queue()  # bind to the running loop; pending jobs are recovered from the DB below
        self._ensure()
        self.workers = concurrency
        n = await self.recover(startup=True)
        if n:
            log.info("Re-queued %s jobs on startup", n)
        self._tasks = [asyncio.create_task(self._worker(i)) for i in range(concurrency)]
        self._tasks.append(asyncio.create_task(self._reaper()))

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def stats(self) -> dict:
        return {"backend": self.backend, "worker_id": self.worker_id, "workers_in_this_process": self.workers,
                "queued": await self.size(), "running_here": len(self.running)}


queue = JobQueue()
