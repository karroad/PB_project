"""Domain providers: registrar (availability, price, purchase) + DNS management.

Each provider the user can pick on a website (Cloudflare, OVH) implements both halves:

* check_domains(...)       -> authoritative availability + price
* register_domain(...)     -> buys the domain (billable, never retried blindly)
* registration_status(...) -> pending | active | failed
* upsert_record(...)       -> points the domain at the hosting target

Purchase errors are split into two kinds so the orchestrator never buys twice:
  DomainOrderRejected  — the provider refused before charging; safe to fix and retry
  DomainOrderUncertain — we cannot tell whether the order went through; needs a human check
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone

import httpx

from ...errors import ConfigurationError, PipelineError


class DomainOrderRejected(PipelineError):
    def __init__(self, message: str, hint: str | None = None, details: dict | None = None):
        super().__init__(message, code="domain_order_rejected", hint=hint or "Nothing was charged. Fix the issue and resume the job.", details=details)


class DomainOrderUncertain(PipelineError):
    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, code="domain_order_uncertain", details=details,
                         hint="We could not confirm whether the order went through. Check the provider dashboard, then use "
                              "Domains → Sync (if it was bought) or Reset (if it was not) before resuming.")


async def rdap_lookup(domain: str) -> dict:
    """Availability + expiry via the public RDAP bootstrap service (no credentials needed)."""
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
            r = await c.get(f"https://rdap.org/domain/{domain}")
    except httpx.HTTPError as e:
        return {"domain": domain, "available": None, "error": f"RDAP lookup failed: {e.__class__.__name__}"}
    if r.status_code == 404:
        return {"domain": domain, "available": True}
    if r.status_code != 200:
        return {"domain": domain, "available": None, "error": f"RDAP HTTP {r.status_code}"}
    data = r.json()
    expiry = next((e.get("eventDate") for e in data.get("events", []) if e.get("eventAction") == "expiration"), None)
    return {"domain": domain, "available": False, "expires_at": expiry, "status": data.get("status", [])}


def apex(domain: str) -> str:
    parts = domain.strip(".").split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else domain


def _num(v) -> float | None:
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


class DNSAdapter:
    key = "none"
    name = "Platform URL only"
    description = "No custom domain — the site is served on the platform URL."
    requires_approval = False
    can_register = False
    credential_fields: list[str] = []

    async def upsert_record(self, creds: dict, domain: str, rtype: str, content: str, proxied: bool = True) -> dict:
        return {"skipped": True}

    async def test_credentials(self, creds: dict) -> tuple[bool, str]:
        return True, "No credentials required"

    async def check_domains(self, creds: dict, domains: list[str]) -> list[dict]:
        raise ConfigurationError(f"{self.name} cannot register domains")

    async def register_domain(self, creds: dict, domain: str, years: int, auto_renew: bool) -> dict:
        raise ConfigurationError(f"{self.name} cannot register domains")

    async def registration_status(self, creds: dict, domain: str, order_ref: str | None) -> dict:
        return {"status": "unknown"}

    def catalog(self) -> dict:
        return {"key": self.key, "name": self.name, "description": self.description, "requires_approval": self.requires_approval,
                "credential_fields": self.credential_fields, "enabled": True, "can_register": self.can_register}


# ============================================================================ Cloudflare
class CloudflareDNS(DNSAdapter):
    key = "cloudflare"
    name = "Cloudflare"
    description = "Buy domains with Cloudflare Registrar (at-cost pricing), manage DNS and proxied TLS via the Cloudflare API."
    can_register = True
    credential_fields = ["api_token", "account_id"]
    API = "https://api.cloudflare.com/client/v4"

    def _h(self, creds):
        if not creds.get("api_token"):
            raise ConfigurationError("Cloudflare account has no api_token")
        return {"Authorization": f"Bearer {creds['api_token']}"}

    def _acct(self, creds) -> str:
        if not creds.get("account_id"):
            raise ConfigurationError("Cloudflare account_id is required for registrar operations",
                                     hint="Edit the Cloudflare provider account and add its account ID.")
        return f"{self.API}/accounts/{creds['account_id']}/registrar"

    @staticmethod
    def _errors(r: httpx.Response) -> str:
        try:
            errs = r.json().get("errors") or []
            return "; ".join(e.get("message", str(e)) for e in errs) or r.text[:300]
        except ValueError:
            return r.text[:300]

    async def test_credentials(self, creds):
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(f"{self.API}/user/tokens/verify", headers=self._h(creds))
            ok = r.status_code == 200 and r.json().get("success")
            return bool(ok), "Token valid" if ok else f"HTTP {r.status_code}"
        except (httpx.HTTPError, ConfigurationError) as e:
            return False, str(e)

    async def check_domains(self, creds, domains):
        out = []
        async with httpx.AsyncClient(timeout=30) as c:
            for i in range(0, len(domains), 20):  # API accepts max 20 per call
                r = await c.post(f"{self._acct(creds)}/domain-check", json={"domains": domains[i:i + 20]}, headers=self._h(creds))
                if r.status_code >= 400:
                    raise PipelineError(f"Cloudflare domain check failed: {self._errors(r)}", code="domain_check_failed")
                for d in r.json()["result"]["domains"]:
                    pricing = d.get("pricing") or {}
                    out.append({"domain": d["name"], "available": bool(d.get("registrable")) and d.get("tier") != "premium",
                                "premium": d.get("tier") == "premium", "price": _num(pricing.get("registration_cost")),
                                "renewal_price": _num(pricing.get("renewal_cost")), "currency": pricing.get("currency"),
                                "reason": d.get("reason")})
        return out

    async def register_domain(self, creds, domain, years, auto_renew):
        body = {"domain_name": domain, "years": years, "auto_renew": auto_renew, "privacy_mode": "redaction"}
        try:
            async with httpx.AsyncClient(timeout=90) as c:
                r = await c.post(f"{self._acct(creds)}/registrations", json=body, headers=self._h(creds))
        except httpx.HTTPError as e:
            raise DomainOrderUncertain(f"Connection lost while registering {domain}: {e.__class__.__name__}")
        if 400 <= r.status_code < 500:
            raise DomainOrderRejected(f"Cloudflare refused the registration: {self._errors(r)}",
                                      hint="Check the account's default payment method and registrant contact in the Cloudflare dashboard.")
        if r.status_code >= 500:
            raise DomainOrderUncertain(f"Cloudflare returned HTTP {r.status_code} while registering {domain}")
        res = r.json().get("result") or {}
        state = res.get("state")
        return {"order_ref": (res.get("links") or {}).get("self") or domain,
                "status": "active" if res.get("completed") and state == "succeeded" else "pending", "raw_state": state}

    async def registration_status(self, creds, domain, order_ref):
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{self._acct(creds)}/registrations/{domain}/registration-status", headers=self._h(creds))
            if r.status_code == 404:
                return {"status": "pending"}
            r.raise_for_status()
            res = r.json().get("result") or {}
            state = res.get("state")
            if state == "succeeded":
                info = await c.get(f"{self._acct(creds)}/registrations/{domain}", headers=self._h(creds))
                reg = (info.json().get("result") or {}) if info.status_code == 200 else {}
                return {"status": "active", "expires_at": reg.get("expires_at") or reg.get("expiry_date")}
            if state in ("failed", "cancelled", "error"):
                return {"status": "failed", "message": json.dumps(res.get("error") or res)[:300]}
            return {"status": "pending", "state": state}

    async def _zone_id(self, c: httpx.AsyncClient, creds, domain: str) -> str:
        z = await c.get(f"{self.API}/zones", params={"name": apex(domain)}, headers=self._h(creds))
        z.raise_for_status()
        zones = z.json()["result"]
        if zones:
            return zones[0]["id"]
        if not creds.get("account_id"):
            raise PipelineError(f"Zone {apex(domain)} not found in this Cloudflare account", code="dns_zone_missing",
                                hint="Add the domain to Cloudflare, or add the account_id so the zone can be created automatically.")
        created = await c.post(f"{self.API}/zones", json={"name": apex(domain), "account": {"id": creds["account_id"]}, "type": "full"}, headers=self._h(creds))
        if created.status_code >= 400:
            raise PipelineError(f"Could not create zone {apex(domain)}: {self._errors(created)}", code="dns_zone_missing")
        return created.json()["result"]["id"]

    async def upsert_record(self, creds, domain, rtype, content, proxied=True):
        async with httpx.AsyncClient(timeout=30) as c:
            zid = await self._zone_id(c, creds, domain)
            ex = await c.get(f"{self.API}/zones/{zid}/dns_records", params={"name": domain, "type": rtype}, headers=self._h(creds))
            ex.raise_for_status()
            body = {"type": rtype, "name": domain, "content": content, "proxied": proxied, "ttl": 1}
            recs = ex.json()["result"]
            if recs:
                r = await c.put(f"{self.API}/zones/{zid}/dns_records/{recs[0]['id']}", json=body, headers=self._h(creds))
            else:
                r = await c.post(f"{self.API}/zones/{zid}/dns_records", json=body, headers=self._h(creds))
            r.raise_for_status()
            return {"zone_id": zid, "record": r.json()["result"]["id"], "proxied": proxied}


# ============================================================================ OVHcloud
class OVHDNS(DNSAdapter):
    key = "ovh"
    name = "OVHcloud"
    description = "Buy domains through the OVH order cart and manage DNS zones with the signed OVH API."
    can_register = True
    credential_fields = ["application_key", "application_secret", "consumer_key", "endpoint", "ovh_subsidiary", "owner_contact"]
    SAFE_BOOL_LABELS = {"OWNER_LEGAL_AGE", "ACCEPT_CONDITIONS"}
    DEFAULTED_LABELS = {"OWNER_CONTACT", "ADMIN_ACCOUNT", "TECH_ACCOUNT", "DNS"}  # OVH uses the calling account when empty

    def _base(self, creds):
        return {"ovh-eu": "https://eu.api.ovh.com/1.0", "ovh-ca": "https://ca.api.ovh.com/1.0", "ovh-us": "https://api.us.ovhcloud.com/1.0"}.get(
            creds.get("endpoint") or "ovh-eu", "https://eu.api.ovh.com/1.0")

    async def _call(self, c: httpx.AsyncClient, creds, method: str, path: str, body=None, raise_status: bool = True):
        for k in ("application_key", "application_secret", "consumer_key"):
            if not creds.get(k):
                raise ConfigurationError(f"OVH account missing {k}")
        payload = "" if body is None else json.dumps(body)
        url = self._base(creds) + path
        ts = str(int(time.time()))
        sig = "$1$" + hashlib.sha1("+".join([creds["application_secret"], creds["consumer_key"], method, url, payload, ts]).encode()).hexdigest()
        r = await c.request(method, url, content=payload or None, headers={
            "X-Ovh-Application": creds["application_key"], "X-Ovh-Consumer": creds["consumer_key"],
            "X-Ovh-Timestamp": ts, "X-Ovh-Signature": sig, "Content-Type": "application/json"})
        if raise_status:
            r.raise_for_status()
        return r if not raise_status else (r.json() if r.content else None)

    async def test_credentials(self, creds):
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                me = await self._call(c, creds, "GET", "/me")
            return True, f"Connected as {me.get('nichandle')}"
        except (httpx.HTTPError, ConfigurationError) as e:
            return False, str(e)

    async def _cart(self, c, creds, description: str) -> str:
        cart = await self._call(c, creds, "POST", "/order/cart", {"ovhSubsidiary": creds.get("ovh_subsidiary") or "FR", "description": description})
        return cart["cartId"]

    @staticmethod
    def _offer(items: list | None) -> dict:
        if not items:
            return {"available": False, "reason": "not_offered"}
        it = items[0]
        mode = str(it.get("pricingMode", ""))
        total = next((p.get("price", {}) for p in it.get("prices", []) if p.get("label") == "TOTAL"), {})
        renew = next((p.get("price", {}) for p in it.get("prices", []) if p.get("label") == "RENEW"), {})
        premium = "premium" in mode
        available = it.get("action") == "create" and it.get("orderable", True) is not False and not premium
        return {"available": available, "premium": premium, "price": _num(total.get("value")), "renewal_price": _num(renew.get("value")),
                "currency": total.get("currencyCode"), "reason": None if available else ("premium" if premium else it.get("action") or "unavailable")}

    async def check_domains(self, creds, domains):
        out = []
        async with httpx.AsyncClient(timeout=30) as c:
            cart_id = await self._cart(c, creds, "siteforge availability check")
            for d in domains:
                items = await self._call(c, creds, "GET", f"/order/cart/{cart_id}/domain?domain={d}")
                out.append({"domain": d, **self._offer(items)})
        return out

    async def register_domain(self, creds, domain, years, auto_renew):
        async with httpx.AsyncClient(timeout=60) as c:
            # Everything before the final checkout is free and safe to fail.
            try:
                cart_id = await self._cart(c, creds, f"siteforge {domain}")
                item = await self._call(c, creds, "POST", f"/order/cart/{cart_id}/domain", {"domain": domain, "duration": f"P{years}Y"})
                item_id = item["itemId"]
                await self._call(c, creds, "POST", f"/order/cart/{cart_id}/assign")
                required = await self._call(c, creds, "GET", f"/order/cart/{cart_id}/item/{item_id}/requiredConfiguration") or []
                unsupported = []
                for cfg in required:
                    label = cfg.get("label")
                    if label in self.SAFE_BOOL_LABELS:
                        await self._call(c, creds, "POST", f"/order/cart/{cart_id}/item/{item_id}/configuration", {"label": label, "value": "true"})
                    elif label == "OWNER_CONTACT" and creds.get("owner_contact"):
                        await self._call(c, creds, "POST", f"/order/cart/{cart_id}/item/{item_id}/configuration", {"label": label, "value": creds["owner_contact"]})
                    elif label not in self.DEFAULTED_LABELS:
                        unsupported.append(label)
                if unsupported:
                    raise DomainOrderRejected(f"This extension needs extra registry data: {', '.join(unsupported)}",
                                              hint="Order this domain manually in the OVH manager, or pick another extension.")
                await self._call(c, creds, "GET", f"/order/cart/{cart_id}/checkout")  # dry-run validation
            except httpx.HTTPStatusError as e:
                raise DomainOrderRejected(f"OVH refused the order: HTTP {e.response.status_code} {e.response.text[:300]}")
            except httpx.HTTPError as e:
                raise DomainOrderRejected(f"OVH unreachable before checkout: {e.__class__.__name__}")
            # The billable call.
            try:
                r = await self._call(c, creds, "POST", f"/order/cart/{cart_id}/checkout",
                                     {"autoPayWithPreferredPaymentMethod": True, "waiveRetractationPeriod": True}, raise_status=False)
            except httpx.HTTPError as e:
                raise DomainOrderUncertain(f"Connection lost during OVH checkout for {domain}: {e.__class__.__name__}", {"cart_id": cart_id})
            if 400 <= r.status_code < 500:
                raise DomainOrderRejected(f"OVH checkout refused: {r.text[:300]}", hint="Check the OVH account's preferred payment method.")
            if r.status_code >= 500:
                raise DomainOrderUncertain(f"OVH checkout returned HTTP {r.status_code}", {"cart_id": cart_id})
            order = r.json() if r.content else {}
            order_id = order.get("orderId") or order.get("order_id")
            return {"order_ref": str(order_id) if order_id else f"cart:{cart_id}", "status": "pending", "raw": {k: order.get(k) for k in ("orderId", "url", "prices") if k in order}}

    async def registration_status(self, creds, domain, order_ref):
        async with httpx.AsyncClient(timeout=30) as c:
            svc = await self._call(c, creds, "GET", f"/domain/{domain}", raise_status=False)
            if svc.status_code == 200:
                return {"status": "active"}
            if order_ref and order_ref.isdigit():
                st = await self._call(c, creds, "GET", f"/me/order/{order_ref}/status")
                if st in ("cancelled", "cancelling"):
                    return {"status": "failed", "message": f"Order {st}"}
                if st == "notPaid":
                    return {"status": "pending", "message": "Order not paid yet — check the preferred payment method in OVH"}
                if st == "documentsRequested":
                    return {"status": "pending", "message": "OVH requests documents for this order"}
                return {"status": "pending", "state": st}
            return {"status": "pending"}

    async def upsert_record(self, creds, domain, rtype, content, proxied=True):
        zone = apex(domain)
        sub = domain[: -len(zone)].rstrip(".")
        async with httpx.AsyncClient(timeout=30) as c:
            ids = await self._call(c, creds, "GET", f"/domain/zone/{zone}/record?fieldType={rtype}&subDomain={sub}")
            if ids:
                await self._call(c, creds, "PUT", f"/domain/zone/{zone}/record/{ids[0]}", {"target": content, "ttl": 300})
            else:
                await self._call(c, creds, "POST", f"/domain/zone/{zone}/record", {"fieldType": rtype, "subDomain": sub, "target": content, "ttl": 300})
            await self._call(c, creds, "POST", f"/domain/zone/{zone}/refresh")
        return {"zone": zone, "subdomain": sub, "updated_at": datetime.now(timezone.utc).isoformat()}


DNS: dict[str, DNSAdapter] = {a.key: a for a in (DNSAdapter(), CloudflareDNS(), OVHDNS())}


def _use_sandbox() -> None:
    from ...config import settings

    if settings.SANDBOX_PROVIDERS:
        from .sandbox import SandboxCloudflare, SandboxOVH

        DNS["cloudflare"], DNS["ovh"] = SandboxCloudflare(), SandboxOVH()


_use_sandbox()
PLANNED_DNS = [{"key": "hostinger", "name": "Hostinger", "description": "Domains & DNS via the Hostinger API — planned adapter",
                "enabled": False, "disabled_reason": "Planned adapter", "requires_approval": True, "credential_fields": ["api_token"]}]


def get_dns(key: str) -> DNSAdapter:
    if key not in DNS:
        raise ConfigurationError(f"Unknown domain provider '{key}'")
    return DNS[key]


def domain_candidates(query: str) -> list[str]:
    """Turn a keyword or name into a short list of domains to check."""
    q = query.strip().lower().removeprefix("https://").removeprefix("http://").strip("/")
    if "." in q:
        return [q]
    base = "".join(ch for ch in q.replace(" ", "") if ch.isalnum() or ch == "-").strip("-")[:40] or "mysite"
    return list(dict.fromkeys([f"{base}.com", f"{base}.net", f"{base}.org", f"{base}.io", f"get{base}.com", f"{base}hq.com", f"the{base}.com", f"{base}.co"]))
