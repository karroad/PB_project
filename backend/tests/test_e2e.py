"""End-to-end: instruction → preview → (review) → publish → live, plus redeploy/rollback.

Run: python -m pytest tests -q   (isolated temp data dir, offline AI generator)
"""
from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import build_site, login, publish, wait_job


def test_build_preview_then_publish(asgi_http):
    with TestClient(app) as client:
        h = login(client)
        r = client.post("/api/websites", headers=h, json={"prompt": "Create a website about sustainable living using Next.js", "stack": "nextjs"})
        assert r.status_code == 201, r.text
        site, job = r.json()["website"], r.json()["job"]
        j = wait_job(client, h, job["id"])
        assert j["status"] == "completed", [(s["key"], s["status"], s["error"]) for s in j["steps"]]
        assert [s["key"] for s in j["steps"]][-3:] == ["development", "testing", "preview"]  # no infra / deploy yet

        detail = client.get(f"/api/websites/{site['id']}", headers=h).json()["website"]
        assert detail["status"] == "preview" and detail["live_url"] is None
        assert detail["config"]["quality"]["blocking"] is False
        prev = client.get(f"/preview/{detail['slug']}/")
        assert prev.status_code == 200 and "<h1>" in prev.text and prev.headers["x-robots-tag"].startswith("noindex")
        assert client.get(f"/preview/{detail['slug']}/blog/").status_code == 200
        assert client.get(f"/sites/{detail['slug']}/").status_code == 404  # not published yet
        assert client.get(f"/api/websites/{site['id']}/deployments", headers=h).json() == []

        # publish the reviewed preview
        pj = publish(client, h, site["id"])
        assert pj["status"] == "completed", [(s["key"], s["error"]) for s in pj["steps"]]
        assert [s["key"] for s in pj["steps"]] == ["infrastructure", "development", "testing", "deployment", "verify"]
        detail = client.get(f"/api/websites/{site['id']}", headers=h).json()["website"]
        assert detail["status"] == "live" and detail["live_url"].endswith(f"/sites/{detail['slug']}/")
        page = client.get(f"/sites/{detail['slug']}/")
        assert page.status_code == 200 and page.headers["x-content-type-options"] == "nosniff"
        assert client.get(f"/sites/{detail['slug']}/sitemap.xml").status_code == 200
        types = {e["type"] for e in client.get(f"/api/jobs/{job['id']}/history", headers=h).json()}
        assert {"job_started", "step_started", "step_completed", "job_completed"} <= types
        titles = [n["title"] for n in client.get("/api/notifications", headers=h).json()["items"]]
        assert any("Preview ready" in t for t in titles) and any("is live" in t for t in titles)

        # redeploy creates v2 and rollback returns to v1
        r = client.post(f"/api/websites/{site['id']}/redeploy", headers=h)
        assert wait_job(client, h, r.json()["id"])["status"] == "completed"
        deps = client.get(f"/api/websites/{site['id']}/deployments", headers=h).json()
        assert [d["version"] for d in deps] == [2, 1]
        v1 = next(d for d in deps if d["version"] == 1)
        assert client.post(f"/api/websites/{site['id']}/rollback/{v1['id']}", headers=h).json()["status"] == "active"


def test_validation_and_publish_approval_option(asgi_http):
    with TestClient(app) as client:
        h = login(client)
        bad = client.post("/api/websites", headers=h, json={"prompt": "short"})
        assert bad.status_code == 422 and bad.json()["error"]["code"] == "validation_error"
        prompt = "An online store selling handmade candles"
        missing = client.post("/api/websites", headers=h, json={"prompt": prompt})
        assert missing.status_code == 422 and "stack" in missing.text  # technology is a mandatory user choice
        auto = client.post("/api/websites", headers=h, json={"prompt": prompt, "stack": "auto"})
        assert auto.status_code == 422 and "select a technology" in auto.json()["error"]["message"].lower()
        assert client.post("/api/websites", headers=h, json={"prompt": prompt, "stack": "shopify"}).status_code == 422  # removed

        r = client.post("/api/websites", headers=h, json={"prompt": prompt, "stack": "wordpress", "require_approval": True})
        site_id = r.json()["website"]["id"]
        assert wait_job(client, h, r.json()["job"]["id"])["status"] == "completed"  # building a preview needs no approval
        site = client.get(f"/api/websites/{site_id}", headers=h).json()["website"]
        assert site["stack"] == "wordpress" and site["stack_selected_by"] == "user" and site["status"] == "preview"

        # publish needs a domain choice; a provider without a domain is refused
        r = client.post(f"/api/websites/{site_id}/publish", headers=h, json={})
        assert r.status_code == 422 and "dns_provider" in r.text
        r = client.post(f"/api/websites/{site_id}/publish", headers=h, json={"dns_provider": "cloudflare"})
        assert r.status_code == 422 and "domain" in r.json()["error"]["message"].lower()

        # a site that opted into manual sign-off waits for approval at publish time
        j = publish(client, h, site_id)
        assert j["status"] == "awaiting_approval"
        appr = [a for a in client.get("/api/approvals", headers=h).json() if a["job_id"] == j["id"]]
        assert appr and appr[0]["action"] == "publish"
        client.post(f"/api/approvals/{appr[0]['id']}/reject", headers=h, json={})
        j = wait_job(client, h, j["id"], statuses=("failed", "completed"))
        assert j["status"] == "failed" and "rejected" in j["error"].lower()
        assert client.get(f"/api/websites/{site_id}", headers=h).json()["website"]["status"] == "preview"  # preview kept
        client.post(f"/api/jobs/{j['id']}/retry", headers=h)
        assert wait_job(client, h, j["id"])["status"] == "awaiting_approval"


def test_publish_requires_preview():
    with TestClient(app) as client:
        h = login(client)
        r = client.post("/api/websites", headers=h, json={"prompt": "A website about indoor climbing gyms", "stack": "static"})
        site_id = r.json()["website"]["id"]
        client.post(f"/api/jobs/{r.json()['job']['id']}/cancel", headers=h)
        wait_job(client, h, r.json()["job"]["id"], statuses=("cancelled", "completed"))
        site = client.get(f"/api/websites/{site_id}", headers=h).json()["website"]
        if not (site.get("config") or {}).get("preview"):
            assert client.post(f"/api/websites/{site_id}/publish", headers=h, json={"dns_provider": "none"}).status_code == 409
