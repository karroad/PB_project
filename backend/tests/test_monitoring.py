"""Monitoring simulation: a live site goes down → alerts + auto-restart policy → recovers."""
import httpx
from fastapi.testclient import TestClient

from app.main import app
from app.monitoring.monitor import run_checks_once
from tests.conftest import login, make_live

_RealClient = httpx.AsyncClient


def test_site_down_restart_and_recovery(asgi_http, monkeypatch):
    with TestClient(app) as client:
        h = login(client)
        site_id = make_live(client, h, "A website about lighthouse photography")["id"]

        status = {"code": 503}

        def factory(*a, **kw):
            return _RealClient(transport=httpx.MockTransport(lambda req: httpx.Response(status["code"], text="x")), timeout=5)

        monkeypatch.setattr(httpx, "AsyncClient", factory)
        before = {n["id"] for n in client.get("/api/notifications?limit=200", headers=h).json()["items"]}
        for _ in range(3):
            client.portal.call(run_checks_once)
        site = client.get(f"/api/websites/{site_id}", headers=h).json()["website"]
        assert site["health_status"] == "down"
        new = [n["title"] for n in client.get("/api/notifications?limit=200", headers=h).json()["items"] if n["id"] not in before]
        assert any("is DOWN" in t for t in new), new
        assert any("Auto-restart" in t for t in new), new  # restart policy fired after 3 consecutive failures

        status["code"] = 200
        client.portal.call(run_checks_once)
        site = client.get(f"/api/websites/{site_id}", headers=h).json()["website"]
        assert site["health_status"] == "up"
        titles = [n["title"] for n in client.get("/api/notifications?limit=200", headers=h).json()["items"]]
        assert any("is UP" in t for t in titles)
        hist = client.get(f"/api/websites/{site_id}/health", headers=h).json()
        assert len(hist["checks"]) == 4 and hist["uptime_percent"] == 25.0
        ov = client.get("/api/monitoring/overview", headers=h).json()
        assert {"cpu_percent", "memory_percent", "disk_percent"} <= set(ov["system"]) and any(s["id"] == site_id for s in ov["sites"])
