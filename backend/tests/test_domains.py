"""Domain purchase at publish time with a fake Cloudflare registrar: preview first, then quote → approval →
single order → activation → DNS → site live on its own domain. Also the price cap and interrupted orders."""
import pytest
from fastapi.testclient import TestClient

from app.adapters.dns import DNS, DomainOrderUncertain
from app.main import app
from tests.conftest import build_site, login, wait_job


class FakeRegistrar:
    def __init__(self, price=9.77):
        self.price = price
        self.registered: list[str] = []
        self.dns: list[tuple] = []
        self.fail_next_order = False
        self.polls = 0

    async def check_domains(self, creds, domains):
        assert creds["api_token"] == "cf-token"  # decrypted provider credentials reach the adapter
        return [{"domain": d, "available": d not in self.registered, "premium": False, "price": self.price,
                 "renewal_price": self.price, "currency": "USD", "reason": None} for d in domains]

    async def register_domain(self, creds, domain, years, auto_renew):
        if self.fail_next_order:
            self.fail_next_order = False
            raise DomainOrderUncertain("connection reset during checkout")
        self.registered.append(domain)
        return {"order_ref": f"wf-{domain}", "status": "pending"}

    async def registration_status(self, creds, domain, order_ref):
        self.polls += 1
        return {"status": "active", "expires_at": "2027-11-21"} if self.polls >= 2 else {"status": "pending", "state": "in_progress"}

    async def upsert_record(self, creds, domain, rtype, content, proxied=True):
        self.dns.append((domain, rtype, content))
        return {"zone_id": "z1", "record": "r1"}


@pytest.fixture
def fake_cf(monkeypatch):
    fake = FakeRegistrar()
    cf = DNS["cloudflare"]
    for name in ("check_domains", "register_domain", "registration_status", "upsert_record"):
        monkeypatch.setattr(cf, name, getattr(fake, name))
    return fake


def _account(client, h):
    r = client.post("/api/providers", headers=h, json={"provider": "cloudflare", "kind": "dns", "label": "CF test",
                                                       "credentials": {"api_token": "cf-token", "account_id": "acc-1"}})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _buy(acc, domain):
    return {"dns_provider": "cloudflare", "dns_account_id": acc, "domain": domain, "domain_mode": "buy"}


def test_buy_domain_at_publish(fake_cf, asgi_http):
    with TestClient(app) as client:
        h = login(client)
        acc = _account(client, h)
        search = client.get("/api/domains/search", headers=h, params={"q": "candle glow", "provider": "cloudflare", "account_id": acc}).json()
        assert search["results"][0]["domain"] == "candleglow.com" and search["results"][0]["buyable"]

        site = build_site(client, h, "A website about handmade candles")
        assert site["status"] == "preview" and fake_cf.registered == []  # building never buys anything

        r = client.post(f"/api/websites/{site['id']}/publish", headers=h, json=_buy(acc, "candleglow.com"))
        assert r.status_code == 200, r.text
        job = r.json()["id"]
        j = wait_job(client, h, job)
        assert j["status"] == "awaiting_approval", [(s["key"], s["status"], s["error"]) for s in j["steps"]]
        appr = [a for a in client.get("/api/approvals", headers=h).json() if a["job_id"] == job][0]
        assert appr["action"] == "register_domain" and appr["details"]["price"] == 9.77
        assert fake_cf.registered == []  # nothing bought before approval
        client.post(f"/api/approvals/{appr['id']}/approve", headers=h, json={})

        j = wait_job(client, h, job, statuses=("completed", "failed"))
        assert j["status"] == "completed", [(s["key"], s["status"], s["error"]) for s in j["steps"]]
        assert fake_cf.registered == ["candleglow.com"]  # bought exactly once
        assert fake_cf.dns == [("candleglow.com", "A", "203.0.113.10")]
        dom = [d for d in client.get("/api/domains", headers=h).json() if d["name"] == "candleglow.com"][0]
        assert dom["status"] == "active" and dom["website_id"] == site["id"] and dom["expires_at"] == "2027-11-21"

        live = client.get(f"/api/websites/{site['id']}", headers=h).json()["website"]
        assert live["status"] == "live" and live["live_url"] == "http://candleglow.com/"
        page = client.get("/", headers={"host": "candleglow.com"})  # served on its own domain
        assert page.status_code == 200 and "<h1>" in page.text
        assert client.get("/blog", headers={"host": "candleglow.com"}, follow_redirects=True).status_code == 200

        # publishing again (e.g. after changes) never buys the domain a second time
        r = client.post(f"/api/websites/{site['id']}/publish", headers=h, json=_buy(acc, "candleglow.com"))
        assert wait_job(client, h, r.json()["id"], statuses=("completed", "failed"))["status"] == "completed"
        assert fake_cf.registered == ["candleglow.com"]

        # the same domain can't be used for another site
        other = build_site(client, h, "Another candle website please")
        dup = client.post(f"/api/websites/{other['id']}/publish", headers=h, json=_buy(acc, "candleglow.com"))
        assert dup.status_code == 409


def test_price_cap_and_interrupted_order(fake_cf, asgi_http):
    with TestClient(app) as client:
        h = login(client)
        acc = _account(client, h)
        site = build_site(client, h, "A website about urban beekeeping")
        fake_cf.price = 999.0
        capped = client.post(f"/api/websites/{site['id']}/publish", headers=h, json=_buy(acc, "urbanbees.com"))
        assert capped.status_code == 422 and "limit" in capped.json()["error"]["message"]

        fake_cf.price = 10.0
        fake_cf.fail_next_order = True
        job = client.post(f"/api/websites/{site['id']}/publish", headers=h, json=_buy(acc, "urbanbees.com")).json()["id"]
        wait_job(client, h, job)
        appr = [a for a in client.get("/api/approvals", headers=h).json() if a["job_id"] == job][0]
        client.post(f"/api/approvals/{appr['id']}/approve", headers=h, json={})
        j = wait_job(client, h, job, statuses=("completed", "failed"))
        infra = next(s for s in j["steps"] if s["key"] == "infrastructure")
        assert j["status"] == "failed" and infra["output"]["error"]["code"] == "domain_order_uncertain"
        dom = [d for d in client.get("/api/domains", headers=h).json() if d["name"] == "urbanbees.com"][0]
        assert dom["status"] == "unknown"
        assert client.get(f"/api/websites/{site['id']}", headers=h).json()["website"]["status"] == "preview"  # preview untouched

        # resuming does NOT place a second order while the state is unknown
        client.post(f"/api/jobs/{job}/retry", headers=h)
        assert wait_job(client, h, job, statuses=("completed", "failed"))["status"] == "failed"
        assert fake_cf.registered == []

        # admin confirms nothing was bought → reset → resume buys it once
        assert client.post(f"/api/domains/{dom['id']}/reset", headers=h).json()["status"] == "quoted"
        client.post(f"/api/jobs/{job}/retry", headers=h)
        j = wait_job(client, h, job, statuses=("completed", "failed", "awaiting_approval"))
        assert j["status"] == "completed", [(s["key"], s["status"], s["error"]) for s in j["steps"]]
        assert fake_cf.registered == ["urbanbees.com"]
