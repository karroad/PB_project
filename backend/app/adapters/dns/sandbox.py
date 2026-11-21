"""Sandbox domain providers (SANDBOX_PROVIDERS=true): simulate Cloudflare/OVH so the whole
domain-buying flow can be demonstrated and tested without real accounts or charges.

Rules (deterministic, so demos are repeatable):
  * names containing "taken"  → unavailable
  * names starting "premium"  → premium (never bought)
  * names starting "fail"     → the order is refused (nothing charged)
  * names starting "lost"     → connection drops at checkout (outcome uncertain)
  * everything else           → available; becomes active ~4 seconds after ordering
"""
from __future__ import annotations

import hashlib
import time

from . import CloudflareDNS, DomainOrderRejected, DomainOrderUncertain, OVHDNS

ACTIVATION_SECONDS = 4


class SandboxMixin:
    sandbox = True
    currency = "USD"

    def _price(self, domain: str) -> float:
        tld_base = {"com": 9.77, "net": 11.84, "org": 10.11, "io": 39.0, "co": 24.5}.get(domain.rsplit(".", 1)[-1], 14.2)
        return round(tld_base + int(hashlib.md5(domain.encode()).hexdigest()[:2], 16) % 3, 2)

    async def test_credentials(self, creds):
        return True, "Sandbox account (simulated, no real API calls)"

    async def check_domains(self, creds, domains):
        out = []
        for d in domains:
            premium = d.startswith("premium")
            available = "taken" not in d and not premium
            out.append({"domain": d, "available": available, "premium": premium, "price": self._price(d) if available else (2500.0 if premium else None),
                        "renewal_price": self._price(d) if available else None, "currency": self.currency,
                        "reason": None if available else ("domain_premium" if premium else "domain_unavailable")})
        return out

    async def register_domain(self, creds, domain, years, auto_renew):
        if domain.startswith("fail"):
            raise DomainOrderRejected(f"[sandbox] {self.name} refused the order: no default payment method")
        if domain.startswith("lost"):
            raise DomainOrderUncertain(f"[sandbox] connection lost during checkout for {domain}")
        return {"order_ref": f"sandbox:{time.time():.0f}", "status": "pending"}

    async def registration_status(self, creds, domain, order_ref):
        if not order_ref or not order_ref.startswith("sandbox:"):
            return {"status": "pending"}
        age = time.time() - float(order_ref.split(":", 1)[1])
        if age >= ACTIVATION_SECONDS:
            return {"status": "active", "expires_at": time.strftime("%Y-%m-%d", time.gmtime(time.time() + 365 * 86400))}
        return {"status": "pending", "state": "registry processing"}

    async def upsert_record(self, creds, domain, rtype, content, proxied=True):
        return {"sandbox": True, "record": f"{domain} {rtype} {content}"}


class SandboxCloudflare(SandboxMixin, CloudflareDNS):
    name = "Cloudflare (sandbox)"


class SandboxOVH(SandboxMixin, OVHDNS):
    name = "OVHcloud (sandbox)"
    currency = "EUR"
