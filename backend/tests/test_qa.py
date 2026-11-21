"""QA sweep: permissions, security edge cases, lifecycle actions, forms, concurrency and recovery."""
import asyncio
import time
from datetime import timedelta

from fastapi.testclient import TestClient

from app.agents.quality import run_checks
from app.database import SessionLocal
from app.main import app
from app.models import Job, utcnow
from app.orchestrator.queue import queue
from tests.conftest import login, make_live, publish, wait_job

SITE = {"stack": "static"}


def _user(client, h, email, role):
    r = client.post("/api/users", headers=h, json={"email": email, "name": role, "password": "password123", "role": role})
    assert r.status_code in (201, 409), r.text
    t = client.post("/api/auth/login", json={"email": email, "password": "password123"}).json()["access_token"]
    return {"Authorization": f"Bearer {t}"}


def _site(client, h, prompt, **kw):
    r = client.post("/api/websites", headers=h, json={"prompt": prompt, **SITE, **kw})
    assert r.status_code == 201, r.text
    return r.json()["website"], r.json()["job"]


def test_permissions_and_auth(asgi_http):
    with TestClient(app) as client:
        admin = login(client)
        op = _user(client, admin, "op@qa.test", "operator")
        op2 = _user(client, admin, "op2@qa.test", "operator")
        viewer = _user(client, admin, "viewer@qa.test", "viewer")

        assert client.get("/api/websites").status_code == 401
        assert client.get("/api/websites", headers={"Authorization": "Bearer nonsense"}).status_code == 401
        assert client.post("/api/websites", headers=viewer, json={"prompt": "A viewer should not create sites", **SITE}).status_code == 403

        site, job = _site(client, op, "A website about mountain photography tours")
        wait_job(client, op, job["id"], statuses=("completed", "failed"))
        # other operators cannot see or touch it; admins can
        assert client.get(f"/api/websites/{site['id']}", headers=op2).status_code == 404
        assert client.post(f"/api/websites/{site['id']}/redeploy", headers=op2).status_code == 404
        assert all(s["id"] != site["id"] for s in client.get("/api/websites", headers=op2).json()["items"])
        assert client.get(f"/api/websites/{site['id']}", headers=admin).status_code == 200
        # only admins delete, manage users, providers and read the audit log
        assert client.request("DELETE", f"/api/websites/{site['id']}", headers=op, json={"confirm": site["slug"]}).status_code == 403
        assert client.get("/api/users", headers=op).status_code == 403
        assert client.get("/api/audit", headers=op).status_code == 403
        assert client.post("/api/providers", headers=op, json={"provider": "cloudflare", "kind": "dns", "label": "x", "credentials": {}}).status_code == 403
        assert client.get("/api/providers", headers=viewer).status_code == 403
        # a disabled user is locked out immediately
        uid = next(u["id"] for u in client.get("/api/users", headers=admin).json() if u["email"] == "viewer@qa.test")
        client.patch(f"/api/users/{uid}", headers=admin, json={"is_active": False})
        assert client.get("/api/auth/me", headers=viewer).status_code == 401
        # admins cannot demote themselves
        me = client.get("/api/auth/me", headers=admin).json()
        assert client.patch(f"/api/users/{me['id']}", headers=admin, json={"role": "viewer"}).status_code == 400


def test_login_lockout():
    with TestClient(app) as client:
        for _ in range(10):
            assert client.post("/api/auth/login", json={"email": "lock@qa.test", "password": "wrong"}).status_code == 401
        assert client.post("/api/auth/login", json={"email": "lock@qa.test", "password": "wrong"}).status_code == 429


def test_security_edges(asgi_http):
    with TestClient(app) as client:
        h = login(client)
        site = make_live(client, h, "A website about restoring vintage bicycles")
        slug = site["slug"]
        for bad in ("../../.env", "..%2f..%2fsiteforge.db", "%2e%2e/%2e%2e/siteforge.db"):
            assert client.get(f"/sites/{slug}/{bad}").status_code in (400, 404), bad
        assert client.get(f"/api/media/{slug}/..%2f..%2fsiteforge.db").status_code == 404
        assert client.get(f"/api/websites/{site['id']}/files", headers=h, params={"path": "../../../app/config.py"}).status_code == 404
        assert client.get(f"/sites/{slug}/").headers.get("content-security-policy")
        # served site never contains platform secrets
        page = client.get(f"/sites/{slug}/").text
        assert "change-me" not in page and "SECRET" not in page


def test_lifecycle_cancel_archive_delete(asgi_http):
    with TestClient(app) as client:
        h = login(client)
        site, job = _site(client, h, "A website about urban rooftop gardening")
        # a second job for the same site is refused while one is active
        assert client.post(f"/api/websites/{site['id']}/redeploy", headers=h).status_code == 409
        cancel = client.post(f"/api/jobs/{job['id']}/cancel", headers=h)
        assert cancel.status_code == 200
        j = wait_job(client, h, job["id"], statuses=("cancelled", "completed", "failed"))
        assert j["status"] in ("cancelled", "completed")  # it may finish a step first, but must stop cleanly
        if j["status"] == "cancelled":
            assert client.post(f"/api/jobs/{job['id']}/retry", headers=h).status_code == 200
            assert wait_job(client, h, job["id"], statuses=("completed", "failed"))["status"] == "completed"
        assert publish(client, h, site["id"])["status"] == "completed"

        slug = client.get(f"/api/websites/{site['id']}", headers=h).json()["website"]["slug"]
        assert client.post(f"/api/websites/{site['id']}/archive", headers=h).json()["status"] == "archived"
        assert client.get(f"/sites/{slug}/").status_code == 410
        assert client.post(f"/api/websites/{site['id']}/redeploy", headers=h).status_code == 409
        assert client.post(f"/api/websites/{site['id']}/restore", headers=h).json()["status"] == "live"
        assert client.get(f"/sites/{slug}/").status_code == 200

        wrong = client.request("DELETE", f"/api/websites/{site['id']}", headers=h, json={"confirm": "nope"})
        assert wrong.status_code == 400
        assert client.request("DELETE", f"/api/websites/{site['id']}", headers=h, json={"confirm": slug}).json()["deleted"]
        assert client.get(f"/api/websites/{site['id']}", headers=h).status_code == 404
        assert client.get(f"/sites/{slug}/").status_code == 404
        actions = {a["action"] for a in client.get("/api/audit", headers=h).json()}
        assert {"website.archive", "website.restore", "website.delete", "job.cancel"} <= actions


def test_contact_form(asgi_http):
    with TestClient(app) as client:
        h = login(client)
        site = make_live(client, h, "A website about pottery classes for beginners")
        slug = site["slug"]
        form = client.get(f"/sites/{slug}/contact/").text
        assert f"/api/public/forms/{slug}" in form
        r = client.post(f"/api/public/forms/{slug}", data={"name": "Ana", "email": "ana@example.com", "message": "Hello!"}, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"].endswith("contact/thanks/")
        assert client.post(f"/api/public/forms/{slug}", data={"name": "x", "email": "", "message": ""}, follow_redirects=False).status_code == 422
        bot = client.post(f"/api/public/forms/{slug}", data={"name": "bot", "email": "b@b.co", "message": "spam", "_hp": "x"}, follow_redirects=False)
        assert bot.status_code == 303  # honeypot: silently accepted, not stored
        subs = client.get(f"/api/websites/{site['id']}/submissions", headers=h).json()
        assert [s["data"]["name"] for s in subs] == ["Ana"]
        assert client.post("/api/public/forms/no-such-site", data={"email": "a@b.co", "message": "x"}).status_code == 404


def test_concurrency_limit_and_crash_recovery(asgi_http):
    with TestClient(app) as client:
        h = login(client)
        jobs = [_site(client, h, f"A website about regional cooking style number {i}")[1]["id"] for i in range(6)]
        peak, t0 = 0, time.time()
        while time.time() - t0 < 90:
            states = [client.get(f"/api/jobs/{j}", headers=h).json()["status"] for j in jobs]
            peak = max(peak, states.count("running"))
            if all(s in ("completed", "failed") for s in states):
                break
            time.sleep(0.05)
        assert all(s == "completed" for s in states), states
        assert peak <= 3, f"{peak} jobs ran at once with MAX_CONCURRENT_JOBS=3"

        # simulate a worker that died mid-job: status running, stale heartbeat
        site, job = _site(client, h, "A website about restoring old typewriters")
        wait_job(client, h, job["id"], statuses=("completed", "failed"))
        db = SessionLocal()
        j = db.get(Job, job["id"])
        j.status, j.heartbeat_at, j.worker_id = "running", utcnow() - timedelta(hours=1), "dead-worker"
        for s in j.steps[-3:]:
            s.status = "pending"
        db.commit(); db.close()
        assert client.portal.call(queue.recover) >= 1
        resumed = wait_job(client, h, job["id"], statuses=("completed", "failed"))
        assert resumed["status"] == "completed" and resumed["attempts"] >= 2
        assert any(e["type"] == "job_resumed" for e in client.get(f"/api/jobs/{job['id']}/history", headers=h).json())


def test_quality_gate_blocks_leaked_secret(tmp_path):
    (tmp_path / "index.html").write_text('<html lang="en"><head><title>T</title><meta name="viewport" content="width=device-width">'
                                         '</head><body><h1>x</h1><script>const k="sk-ant-api03-abcdefghijklmnop"</script></body></html>')
    report = run_checks(tmp_path, {}, ["my-provider-secret-123"])
    assert report["blocking"] and "No leaked credentials" in report["critical_failures"]
    (tmp_path / "index.html").write_text('<html lang="en"><body><h1>x</h1><a href="missing/">x</a>my-provider-secret-123</body></html>')
    report = run_checks(tmp_path, {}, ["my-provider-secret-123"])
    assert {"No leaked credentials", "Internal links & navigation"} <= set(report["critical_failures"])
