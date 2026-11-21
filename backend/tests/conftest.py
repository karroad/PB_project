"""Shared test environment: isolated data dir, offline AI, public-server mode for domain tests."""
import os
import tempfile

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="siteforge-test-")
os.environ["AI_PROVIDER"] = "offline"
os.environ["SIMULATED_STEP_DELAY"] = "0"
os.environ["RUN_MONITOR"] = "false"
os.environ["FAL_KEY"] = ""
os.environ["PUBLIC_BASE_URL"] = "http://testserver"
os.environ["SERVER_PUBLIC_IP"] = "203.0.113.10"  # documentation IP; enables buying domains + host routing
os.environ["STEP_RETRIES"] = "0"

import time  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402


@pytest.fixture
def asgi_http(monkeypatch):
    """Route the verify agent's outbound HTTP calls into the app itself."""
    from app.main import app

    real = httpx.AsyncClient

    def fake_client(*a, **kw):
        return real(transport=httpx.ASGITransport(app=app), base_url="http://testserver", follow_redirects=True, timeout=10)

    monkeypatch.setattr("app.agents.pipeline_agents.httpx.AsyncClient", fake_client)


def login(client):
    r = client.post("/api/auth/login", json={"email": "admin@siteforge.local", "password": "admin123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def wait_job(client, h, job_id, statuses=("completed", "failed", "awaiting_approval"), timeout=60):
    t0 = time.time()
    j = {}
    while time.time() - t0 < timeout:
        j = client.get(f"/api/jobs/{job_id}", headers=h).json()
        if j["status"] in statuses:
            return j
        time.sleep(0.2)
    raise AssertionError(f"job stuck: {j.get('status')} {j.get('current_step')}")


def build_site(client, h, prompt, stack="static"):
    """Create a website and wait for its preview (nothing is published)."""
    r = client.post("/api/websites", headers=h, json={"prompt": prompt, "stack": stack})
    assert r.status_code == 201, r.text
    j = wait_job(client, h, r.json()["job"]["id"], statuses=("completed", "failed"))
    assert j["status"] == "completed", [(s["key"], s["error"]) for s in j["steps"]]
    return client.get(f"/api/websites/{r.json()['website']['id']}", headers=h).json()["website"]


def publish(client, h, site_id, expect="completed", **target):
    """Publish the reviewed preview (platform URL by default) and wait for the job."""
    body = {"dns_provider": "none", **target}
    r = client.post(f"/api/websites/{site_id}/publish", headers=h, json=body)
    assert r.status_code == 200, r.text
    return wait_job(client, h, r.json()["id"], statuses=("completed", "failed", "awaiting_approval"))


def make_live(client, h, prompt, stack="static"):
    site = build_site(client, h, prompt, stack)
    assert publish(client, h, site["id"])["status"] == "completed"
    return client.get(f"/api/websites/{site['id']}", headers=h).json()["website"]
