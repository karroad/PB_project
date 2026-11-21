"""Redis-backed queue + event bus (via fakeredis) and AI-provider failure handling."""
import asyncio

import fakeredis
import pytest
from fastapi.testclient import TestClient

from app.ai import llm
from app.config import settings
from app.database import SessionLocal
from app.main import app
from app.models import Job
from app.orchestrator.queue import JobQueue
from app.orchestrator.runner import _claim
from tests.conftest import login, wait_job


@pytest.fixture
def fake_redis(monkeypatch):
    server = fakeredis.FakeServer()
    monkeypatch.setattr("redis.asyncio.from_url", lambda url, decode_responses=True, **kw: fakeredis.aioredis.FakeRedis(server=server, decode_responses=True))
    monkeypatch.setattr(settings, "REDIS_URL", "redis://fake:6379/0")
    return server


def test_redis_event_bus_fans_out(fake_redis):
    from app.events import RedisBus

    async def scenario():
        api_replica, worker = RedisBus(settings.REDIS_URL), RedisBus(settings.REDIS_URL)
        await api_replica.start()
        await worker.start()
        await asyncio.sleep(0.2)  # let the pattern subscription register
        q = api_replica.subscribe("job:abc")
        worker.publish("job:abc", {"type": "step_started", "job_id": "abc"})  # published by another process
        ev = await asyncio.wait_for(q.get(), 3)
        await api_replica.stop()
        await worker.stop()
        return ev

    ev = asyncio.run(scenario())
    assert ev["type"] == "step_started" and ev["job_id"] == "abc"


def test_redis_queue_and_exactly_once_claim(fake_redis):
    async def scenario():
        q1, q2 = JobQueue(), JobQueue()
        q1.backend = q2.backend = "redis"
        await q1.enqueue("job-1")
        await q1.enqueue("job-2")
        assert await q2.size() == 2  # the queue is shared between processes
        got = [await q2._next(), await q1._next()]
        assert sorted(got) == ["job-1", "job-2"] and await q1.size() == 0
        assert await q1._redis.llen(JobQueue.PROCESSING_KEY) == 2  # in-flight jobs are tracked
        return got

    asyncio.run(scenario())


def test_claim_is_atomic(asgi_http):
    with TestClient(app) as client:
        h = login(client)
        r = client.post("/api/websites", headers=h, json={"prompt": "A website about alpine wildflowers", "stack": "static"})
        job_id = r.json()["job"]["id"]
        wait_job(client, h, job_id, statuses=("completed", "failed"))
        db = SessionLocal()
        try:
            db.get(Job, job_id).status = "queued"
            db.commit()
            assert _claim(db, job_id, "worker-a") is True
            assert _claim(db, job_id, "worker-b") is False  # a second worker can never run the same job
            db.get(Job, job_id).status = "completed"
            db.commit()
        finally:
            db.close()


class BrokenProvider(llm.TextProvider):
    name = "broken"
    offline = False

    def __init__(self, reply):
        self.reply = reply
        self.calls = 0

    async def complete(self, system, prompt):
        self.calls += 1
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


@pytest.mark.parametrize("reply", [llm.LLMError("AI provider rate limited"), "this is not json at all", '{"site_name": 42, "features": "oops"}'])
def test_ai_failures_degrade_gracefully(monkeypatch, asgi_http, reply):
    provider = BrokenProvider(reply)
    monkeypatch.setattr(llm, "_provider", provider)
    with TestClient(app) as client:
        h = login(client)
        r = client.post("/api/websites", headers=h, json={"prompt": "A website about sourdough baking at home", "stack": "static"})
        j = wait_job(client, h, r.json()["job"]["id"], statuses=("completed", "failed"))
        assert j["status"] == "completed", [(s["key"], s["error"]) for s in j["steps"]]
        assert provider.calls >= 4  # every AI agent tried the provider
        site = client.get(f"/api/websites/{r.json()['website']['id']}", headers=h).json()["website"]
        assert isinstance(site["config"]["requirements"]["site_name"], str)  # wrong types never reach the site
        assert isinstance(site["config"]["requirements"]["features"], list)
        if isinstance(reply, Exception) or reply.startswith("this"):
            logs = [l["message"] for s in j["steps"] for l in s["logs"]]
            assert any("using built-in generator" in m for m in logs)
