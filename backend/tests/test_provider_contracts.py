"""Provider contract simulations: the real adapter code runs against in-memory fakes of the Cloudflare,
OVH and Hetzner HTTP APIs (request shapes taken from the providers' documentation)."""
import asyncio
import hashlib
import json

import httpx
import pytest

from app.adapters.dns import DNS, DomainOrderRejected, DomainOrderUncertain
from app.adapters.hosting import HOSTING

_RealClient = httpx.AsyncClient


def route(monkeypatch, handler):
    def factory(*a, **kw):
        kw.pop("follow_redirects", None)
        return _RealClient(transport=httpx.MockTransport(handler), timeout=kw.get("timeout", 10))
    monkeypatch.setattr(httpx, "AsyncClient", factory)


def run(coro):
    return asyncio.run(coro)


# ======================================================================= Cloudflare
class FakeCloudflare:
    ACC = "/client/v4/accounts/acc-1/registrar"

    def __init__(self):
        self.registered: dict[str, str] = {}
        self.zones: dict[str, str] = {}
        self.records: dict[str, dict] = {}
        self.calls: list[str] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        assert req.headers["authorization"] == "Bearer cf-token"
        p, m = req.url.path, req.method
        self.calls.append(f"{m} {p}")
        ok = lambda result, status=200: httpx.Response(status, json={"success": True, "errors": [], "messages": [], "result": result})
        if m == "POST" and p == f"{self.ACC}/domain-check":
            names = json.loads(req.content)["domains"]
            assert 1 <= len(names) <= 20
            out = []
            for n in names:
                if n.startswith("premium"):
                    out.append({"name": n, "registrable": True, "tier": "premium", "pricing": {"currency": "USD", "registration_cost": "2500.00", "renewal_cost": "2500.00"}})
                elif n in self.registered or n.startswith("taken"):
                    out.append({"name": n, "registrable": False, "tier": "standard", "reason": "domain_unavailable"})
                else:
                    out.append({"name": n, "registrable": True, "tier": "standard", "pricing": {"currency": "USD", "registration_cost": "10.44", "renewal_cost": "10.44"}})
            return ok({"domains": out})
        if m == "POST" and p == f"{self.ACC}/registrations":
            body = json.loads(req.content)
            d = body["domain_name"]
            assert set(body) <= {"domain_name", "years", "auto_renew", "privacy_mode", "contacts"}
            if d.startswith("nopay"):
                return httpx.Response(400, json={"success": False, "errors": [{"code": 10000, "message": "No default payment method"}], "result": None})
            if d.startswith("boom"):
                return httpx.Response(502, text="bad gateway")
            if d.startswith("drop"):
                raise httpx.ReadError("connection reset", request=req)
            self.registered[d] = "in_progress" if d.startswith("slow") else "succeeded"
            done = self.registered[d] == "succeeded"
            return ok({"completed": done, "state": self.registered[d], "links": {"self": f"{self.ACC}/registrations/{d}/registration-status"}}, 201 if done else 202)
        if m == "GET" and p.endswith("/registration-status"):
            d = p.split("/registrations/")[1].split("/")[0]
            if d not in self.registered:
                return httpx.Response(404, json={"success": False, "errors": [{"message": "Domain not found"}]})
            st = self.registered[d]
            if st == "in_progress":
                self.registered[d] = "succeeded"  # becomes active on the next poll
            return ok({"completed": st == "succeeded", "state": st})
        if m == "GET" and p.startswith(f"{self.ACC}/registrations/"):
            return ok({"domain_name": p.rsplit("/", 1)[1], "expires_at": "2027-11-21T00:00:00Z", "auto_renew": True})
        if m == "GET" and p == "/client/v4/zones":
            name = req.url.params["name"]
            return ok([{"id": self.zones[name], "name": name}] if name in self.zones else [])
        if m == "POST" and p == "/client/v4/zones":
            body = json.loads(req.content)
            assert body["account"]["id"] == "acc-1"
            self.zones[body["name"]] = f"zone-{body['name']}"
            return ok({"id": self.zones[body["name"]]})
        if p.endswith("/dns_records"):
            if m == "GET":
                key = req.url.params["name"]
                return ok([{"id": "rec-1"}] if key in self.records else [])
            body = json.loads(req.content)
            self.records[body["name"]] = body
            return ok({"id": "rec-1"})
        if m == "PUT" and "/dns_records/" in p:
            body = json.loads(req.content)
            self.records[body["name"]] = body
            return ok({"id": "rec-1"})
        return httpx.Response(404, json={"success": False, "errors": [{"message": f"unmocked {m} {p}"}]})


CF = {"api_token": "cf-token", "account_id": "acc-1"}


def test_cloudflare_check_register_and_dns(monkeypatch):
    fake = FakeCloudflare()
    route(monkeypatch, fake)
    cf = DNS["cloudflare"]
    res = run(cf.check_domains(CF, ["candleglow.com", "taken-name.com", "premium-name.com"]))
    assert res[0] == {"domain": "candleglow.com", "available": True, "premium": False, "price": 10.44, "renewal_price": 10.44, "currency": "USD", "reason": None}
    assert res[1]["available"] is False and res[1]["reason"] == "domain_unavailable"
    assert res[2]["available"] is False and res[2]["premium"] is True  # premium domains are never bought

    order = run(cf.register_domain(CF, "candleglow.com", 1, True))
    assert order["status"] == "active"
    assert run(cf.registration_status(CF, "candleglow.com", order["order_ref"]))["status"] == "active"

    slow = run(cf.register_domain(CF, "slowdomain.com", 1, True))
    assert slow["status"] == "pending"
    assert run(cf.registration_status(CF, "slowdomain.com", slow["order_ref"]))["status"] == "pending"
    assert run(cf.registration_status(CF, "slowdomain.com", slow["order_ref"]))["status"] == "active"

    # zone is created automatically for a freshly bought domain, then the A record is upserted twice (create, update)
    run(cf.upsert_record(CF, "candleglow.com", "A", "203.0.113.10"))
    run(cf.upsert_record(CF, "candleglow.com", "A", "203.0.113.11"))
    assert fake.zones == {"candleglow.com": "zone-candleglow.com"}
    assert fake.records["candleglow.com"]["content"] == "203.0.113.11" and fake.records["candleglow.com"]["proxied"] is True


def test_cloudflare_order_failures_are_classified(monkeypatch):
    route(monkeypatch, FakeCloudflare())
    cf = DNS["cloudflare"]
    with pytest.raises(DomainOrderRejected, match="No default payment method"):
        run(cf.register_domain(CF, "nopay.com", 1, True))  # 4xx: nothing charged, safe to retry later
    with pytest.raises(DomainOrderUncertain):
        run(cf.register_domain(CF, "boom.com", 1, True))  # 5xx: outcome unknown
    with pytest.raises(DomainOrderUncertain):
        run(cf.register_domain(CF, "drop.com", 1, True))  # connection lost mid-request
    from app.errors import ConfigurationError
    with pytest.raises(ConfigurationError):
        run(cf.check_domains({"api_token": "cf-token"}, ["x.com"]))  # account id is required


# ======================================================================= OVH
class FakeOVH:
    BASE = "https://eu.api.ovh.com/1.0"

    def __init__(self, required=None, checkout_status=200):
        self.carts: dict[str, dict] = {}
        self.orders: dict[int, str] = {}
        self.domains: set[str] = set()
        self.records: list[dict] = []
        self.required = required or [{"label": "OWNER_LEGAL_AGE", "type": "bool"}, {"label": "ACCEPT_CONDITIONS", "type": "bool"}, {"label": "OWNER_CONTACT", "type": "/me/contact"}]
        self.checkout_status = checkout_status
        self.checkouts = 0

    def _verify(self, req: httpx.Request):
        body = req.content.decode() if req.content else ""
        ts = req.headers["x-ovh-timestamp"]
        expected = "$1$" + hashlib.sha1("+".join(["app-secret", "consumer", req.method, str(req.url), body, ts]).encode()).hexdigest()
        assert req.headers["x-ovh-signature"] == expected, "bad OVH signature"
        assert req.headers["x-ovh-application"] == "app-key"

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self._verify(req)
        p, m = req.url.path.removeprefix("/1.0"), req.method
        body = json.loads(req.content) if req.content else {}
        if m == "POST" and p == "/order/cart":
            assert body["ovhSubsidiary"] == "FR"
            cid = f"cart{len(self.carts) + 1}"
            self.carts[cid] = {"items": {}, "configs": [], "assigned": False}
            return httpx.Response(200, json={"cartId": cid})
        if m == "GET" and p.endswith("/domain") and "/order/cart/" in p:
            d = req.url.params["domain"]
            if d.startswith("taken") or d in self.domains:
                return httpx.Response(200, json=[{"action": "transfer", "pricingMode": "transfer-default", "orderable": True, "prices": []}])
            return httpx.Response(200, json=[{"action": "create", "pricingMode": "create-default", "orderable": True, "offerId": "com-create",
                                             "prices": [{"label": "PRICE", "price": {"currencyCode": "EUR", "value": 11.99}},
                                                        {"label": "TOTAL", "price": {"currencyCode": "EUR", "value": 9.99}},
                                                        {"label": "RENEW", "price": {"currencyCode": "EUR", "value": 11.99}}]}])
        if m == "POST" and p.endswith("/domain") and "/order/cart/" in p:
            cid = p.split("/")[3]
            assert body["duration"] == "P1Y"
            self.carts[cid]["items"][1] = body["domain"]
            return httpx.Response(200, json={"itemId": 1, "duration": "P1Y", "settings": {"domain": body["domain"]}})
        if m == "POST" and p.endswith("/assign"):
            self.carts[p.split("/")[3]]["assigned"] = True
            return httpx.Response(200)
        if m == "GET" and p.endswith("/requiredConfiguration"):
            return httpx.Response(200, json=self.required)
        if m == "POST" and p.endswith("/configuration"):
            self.carts[p.split("/")[3]]["configs"].append(body)
            return httpx.Response(200, json={"id": 1, **body})
        if p.endswith("/checkout"):
            cart = self.carts[p.split("/")[3]]
            assert cart["assigned"]
            if m == "GET":
                return httpx.Response(200, json={"prices": {"withTax": {"value": 9.99}}})
            self.checkouts += 1
            if self.checkout_status != 200:
                return httpx.Response(self.checkout_status, json={"message": "Your payment method was declined"})
            assert body == {"autoPayWithPreferredPaymentMethod": True, "waiveRetractationPeriod": True}
            oid = 1000 + len(self.orders)
            self.orders[oid] = "delivering"
            self.domains.add(cart["items"][1])
            return httpx.Response(200, json={"orderId": oid, "url": "https://ovh/order"})
        if m == "GET" and p.startswith("/me/order/") and p.endswith("/status"):
            return httpx.Response(200, json=self.orders[int(p.split("/")[3])])
        if m == "GET" and p.startswith("/domain/zone/") and p.endswith("/record"):
            return httpx.Response(200, json=[])
        if m == "POST" and p.startswith("/domain/zone/") and p.endswith("/record"):
            self.records.append(body)
            return httpx.Response(200, json={"id": 77})
        if m == "POST" and p.endswith("/refresh"):
            return httpx.Response(200)
        if m == "GET" and p.startswith("/domain/"):
            d = p.split("/")[2]
            delivered = any(s == "delivered" for s in self.orders.values()) and d in self.domains
            return httpx.Response(200, json={"domain": d}) if delivered else httpx.Response(404, json={"message": "not found"})
        if m == "GET" and p == "/me":
            return httpx.Response(200, json={"nichandle": "xx123-ovh"})
        return httpx.Response(404, json={"message": f"unmocked {m} {p}"})


OVH = {"application_key": "app-key", "application_secret": "app-secret", "consumer_key": "consumer", "ovh_subsidiary": "FR", "owner_contact": "/me/contact/42"}


def test_ovh_signed_check_order_and_dns(monkeypatch):
    fake = FakeOVH()
    route(monkeypatch, fake)
    ovh = DNS["ovh"]
    assert run(ovh.test_credentials(OVH)) == (True, "Connected as xx123-ovh")
    res = run(ovh.check_domains(OVH, ["mybakery.com", "taken-bakery.com"]))
    assert res[0]["available"] and res[0]["price"] == 9.99 and res[0]["renewal_price"] == 11.99 and res[0]["currency"] == "EUR"
    assert res[1]["available"] is False

    order = run(ovh.register_domain(OVH, "mybakery.com", 1, True))
    assert order == {"order_ref": "1000", "status": "pending", "raw": {"orderId": 1000, "url": "https://ovh/order"}}
    cart = next(c for c in fake.carts.values() if c["items"])  # the order cart (the first cart was only for the price check)
    assert {"label": "OWNER_CONTACT", "value": "/me/contact/42"} in cart["configs"]
    assert {"label": "OWNER_LEGAL_AGE", "value": "true"} in cart["configs"]
    assert run(ovh.registration_status(OVH, "mybakery.com", "1000"))["status"] == "pending"
    fake.orders[1000] = "delivered"
    assert run(ovh.registration_status(OVH, "mybakery.com", "1000"))["status"] == "active"
    fake.orders[1001] = "notPaid"
    assert "payment" in run(ovh.registration_status(OVH, "other.com", "1001"))["message"]

    run(ovh.upsert_record(OVH, "www.mybakery.com", "A", "203.0.113.10"))
    assert fake.records == [{"fieldType": "A", "subDomain": "www", "target": "203.0.113.10", "ttl": 300}]


def test_ovh_refuses_safely(monkeypatch):
    # an extension needing extra registry data stops BEFORE checkout (nothing charged)
    fake = FakeOVH(required=[{"label": "OWNER_LEGAL_AGE", "type": "bool"}, {"label": "DOMAIN_CONFIG", "type": "json"}])
    route(monkeypatch, fake)
    with pytest.raises(DomainOrderRejected, match="DOMAIN_CONFIG"):
        run(DNS["ovh"].register_domain(OVH, "mybakery.fr", 1, True))
    assert fake.checkouts == 0
    # payment declined at checkout → rejected; server error at checkout → uncertain
    route(monkeypatch, FakeOVH(checkout_status=403))
    with pytest.raises(DomainOrderRejected, match="declined"):
        run(DNS["ovh"].register_domain(OVH, "mybakery.com", 1, True))
    route(monkeypatch, FakeOVH(checkout_status=500))
    with pytest.raises(DomainOrderUncertain):
        run(DNS["ovh"].register_domain(OVH, "mybakery.com", 1, True))


# ======================================================================= Hetzner
def test_hetzner_provision_reuses_existing_server(monkeypatch):
    servers: list[dict] = []

    def hz(req: httpx.Request):
        assert req.headers["authorization"] == "Bearer hz-token"
        p, m = req.url.path, req.method
        if m == "GET" and p == "/v1/servers":
            sel = req.url.params.get("label_selector", "")
            return httpx.Response(200, json={"servers": [s for s in servers if f"site={s['labels']['site']}" == sel]})
        if m == "POST" and p == "/v1/servers":
            body = json.loads(req.content)
            assert body["image"] == "ubuntu-24.04" and "caddy" in body["user_data"] and body["labels"]["siteforge"] == "true"
            s = {"id": len(servers) + 1, "name": body["name"], "status": "running", "labels": body["labels"], "public_net": {"ipv4": {"ip": "198.51.100.7"}}}
            servers.append(s)
            return httpx.Response(201, json={"server": s})
        if m == "GET" and p.startswith("/v1/servers/"):
            return httpx.Response(200, json={"server": servers[int(p.rsplit("/", 1)[1]) - 1]})
        return httpx.Response(404)

    route(monkeypatch, hz)

    class Site:
        slug, domain = "bakery", "mybakery.com"

    logs = []

    async def log(m):
        logs.append(m)

    hetzner = HOSTING["hetzner"]
    creds = {"api_token": "hz-token"}
    first = run(hetzner.provision(Site, creds, log))
    second = run(hetzner.provision(Site, creds, log))
    assert first == second == {"server_id": 1, "ipv4": "198.51.100.7"}
    assert len(servers) == 1 and any("Reusing" in m for m in logs)  # idempotent: never creates a second paid server


# ======================================================================= Sandbox providers
def test_sandbox_providers_simulate_every_outcome(monkeypatch):
    import time as _time

    from app.adapters.dns.sandbox import ACTIVATION_SECONDS, SandboxCloudflare, SandboxOVH

    cf, ovh = SandboxCloudflare(), SandboxOVH()
    res = run(cf.check_domains({}, ["mybakery.com", "taken-bakery.com", "premiumbakery.com"]))
    assert res[0]["available"] and res[0]["currency"] == "USD" and 9 < res[0]["price"] < 13
    assert res[1]["available"] is False and res[2]["premium"] is True
    assert run(ovh.check_domains({}, ["mybakery.com"]))[0]["currency"] == "EUR"
    with pytest.raises(DomainOrderRejected):
        run(cf.register_domain({}, "failbakery.com", 1, True))
    with pytest.raises(DomainOrderUncertain):
        run(cf.register_domain({}, "lostbakery.com", 1, True))
    order = run(cf.register_domain({}, "mybakery.com", 1, True))
    assert run(cf.registration_status({}, "mybakery.com", order["order_ref"]))["status"] == "pending"
    real = _time.time
    monkeypatch.setattr("app.adapters.dns.sandbox.time.time", lambda: real() + ACTIVATION_SECONDS + 1)
    assert run(cf.registration_status({}, "mybakery.com", order["order_ref"]))["status"] == "active"
