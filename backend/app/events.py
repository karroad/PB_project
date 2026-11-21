"""Event bus used to stream pipeline progress to dashboards (SSE).

* memory backend — single process (default, zero setup)
* redis backend  — set REDIS_URL; API servers and worker processes share events via
  Redis pub/sub, so any API replica can stream any job that any worker is running.

Every event is also persisted to the `job_events` table by the pipeline, so history
survives restarts and clients can replay missed events with `?after=<event id>`.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from datetime import datetime, timezone

from .config import settings

log = logging.getLogger("siteforge.events")


class MemoryBus:
    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue]] = defaultdict(set)

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    def subscribe(self, channel: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=2000)
        self._subs[channel].add(q)
        return q

    def unsubscribe(self, channel: str, q: asyncio.Queue) -> None:
        self._subs[channel].discard(q)

    def _deliver(self, channel: str, event: dict) -> None:
        targets = list(self._subs.get(channel, ()))
        if channel != "*":
            targets += list(self._subs.get("*", ()))
        for q in targets:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:  # slow consumer: drop, it can replay from the DB
                pass

    def publish(self, channel: str, event: dict) -> None:
        event.setdefault("ts", datetime.now(timezone.utc).isoformat())
        self._deliver(channel, event)


class RedisBus(MemoryBus):
    """Fans events out through one Redis pattern subscription per process."""

    PREFIX = "siteforge:events:"

    def __init__(self, url: str) -> None:
        super().__init__()
        import redis.asyncio as aioredis

        self._redis = aioredis.from_url(url, decode_responses=True)
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._listen())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
        await self._redis.aclose()

    async def _listen(self) -> None:
        while True:
            try:
                pubsub = self._redis.pubsub()
                await pubsub.psubscribe(self.PREFIX + "*")
                async for msg in pubsub.listen():
                    if msg.get("type") != "pmessage":
                        continue
                    channel = msg["channel"][len(self.PREFIX):]
                    self._deliver(channel, json.loads(msg["data"]))
            except asyncio.CancelledError:
                raise
            except Exception as e:  # reconnect on Redis hiccups
                log.warning("Redis event listener error: %s — reconnecting", e)
                await asyncio.sleep(2)

    def publish(self, channel: str, event: dict) -> None:
        event.setdefault("ts", datetime.now(timezone.utc).isoformat())
        payload = json.dumps(event, default=str)
        try:
            asyncio.get_running_loop().create_task(self._redis.publish(self.PREFIX + channel, payload))
        except RuntimeError:
            self._deliver(channel, event)


def _make_bus() -> MemoryBus:
    if settings.REDIS_URL:
        try:
            return RedisBus(settings.REDIS_URL)
        except ImportError:
            log.warning("redis package not installed — falling back to in-memory event bus")
    return MemoryBus()


bus = _make_bus()
