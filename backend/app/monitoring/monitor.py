"""Centralised monitoring + maintenance agent: uptime, response time, SSL/domain expiry,
server resources, auto-restart policy and status-change notifications."""
from __future__ import annotations

import asyncio
import logging
import socket
import ssl
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import httpx
import psutil
from sqlalchemy import delete, select
from sqlalchemy.orm.attributes import flag_modified

from ..adapters.dns import rdap_lookup
from ..adapters.hosting import get_hosting
from ..config import settings
from ..database import SessionLocal
from ..events import bus
from ..models import Deployment, HealthCheck, Website, utcnow
from ..notify import notify

log = logging.getLogger("siteforge.monitor")
RESTART_AFTER_FAILURES = 3


def system_stats() -> dict:
    disk = psutil.disk_usage(str(settings.DATA_DIR))
    mem = psutil.virtual_memory()
    return {"cpu_percent": psutil.cpu_percent(interval=None), "memory_percent": mem.percent, "memory_used_gb": round(mem.used / 1e9, 2),
            "memory_total_gb": round(mem.total / 1e9, 2), "disk_percent": disk.percent, "disk_free_gb": round(disk.free / 1e9, 1),
            "load": [round(x, 2) for x in psutil.getloadavg()] if hasattr(psutil, "getloadavg") else None}


def ssl_expiry(host: str) -> str | None:
    ctx = ssl.create_default_context()
    with socket.create_connection((host, 443), timeout=8) as sock, ctx.wrap_socket(sock, server_hostname=host) as s:
        not_after = s.getpeercert()["notAfter"]
    return datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc).isoformat()


async def check_site(client: httpx.AsyncClient, site_id: str) -> None:
    db = SessionLocal()
    try:
        site = db.get(Website, site_id)
        if not site or not site.live_url or not site.live_url.startswith("http"):
            return
        t0 = time.perf_counter()
        ok, code, err = False, None, None
        try:
            r = await client.get(site.live_url)
            code, ok = r.status_code, r.status_code < 400
        except httpx.HTTPError as e:
            err = e.__class__.__name__
        ms = round((time.perf_counter() - t0) * 1000, 1)
        db.add(HealthCheck(website_id=site.id, ok=ok, status_code=code, response_ms=ms if code else None, error=err))
        prev = site.health_status
        new = "up" if ok and ms < 3000 else ("degraded" if ok else "down")
        site.health_status, site.last_checked_at = new, utcnow()
        cfg = dict(site.config or {})
        mon = dict(cfg.get("monitoring") or {})
        mon["consecutive_failures"] = 0 if ok else mon.get("consecutive_failures", 0) + 1

        host = urlparse(site.live_url).hostname
        last = mon.get("expiry_checked_at")
        if site.live_url.startswith("https") and host and (not last or last < (utcnow() - timedelta(hours=24)).isoformat()):
            try:
                mon["ssl_expires_at"] = await asyncio.to_thread(ssl_expiry, host)
            except (OSError, ssl.SSLError, KeyError, ValueError) as e:
                mon["ssl_error"] = str(e)[:200]
            if site.domain:
                info = await rdap_lookup(site.domain)
                mon["domain_expires_at"] = info.get("expires_at")
            mon["expiry_checked_at"] = utcnow().isoformat()
        cfg["monitoring"] = mon
        site.config = cfg
        flag_modified(site, "config")
        db.commit()

        if prev != new and prev != "unknown":
            level = "success" if new == "up" else ("warning" if new == "degraded" else "error")
            notify(db, website=site, title=f"{site.name} is {new.upper()}", message=f"{site.live_url} → {code or err} in {ms} ms", level=level)
        bus.publish("*", {"type": "health", "website_id": site.id, "health": new, "response_ms": ms, "status_code": code})

        if mon["consecutive_failures"] >= RESTART_AFTER_FAILURES and site.current_deployment_id:
            dep = db.get(Deployment, site.current_deployment_id)
            hosting = get_hosting(site.hosting_provider)
            try:
                msg = await hosting.restart(site, dep)
                notify(db, website=site, title=f"Auto-restart: {site.name}", message=msg, level="warning")
            except Exception as e:  # noqa: BLE001
                notify(db, website=site, title=f"Auto-restart failed: {site.name}", message=str(e), level="error")
            mon["consecutive_failures"] = 0
            site.config = {**cfg, "monitoring": mon}
            db.commit()
    finally:
        db.close()


async def run_checks_once() -> int:
    db = SessionLocal()
    try:
        ids = db.scalars(select(Website.id).where(Website.status == "live")).all()
        db.execute(delete(HealthCheck).where(HealthCheck.checked_at < utcnow() - timedelta(days=7)))
        db.commit()
    finally:
        db.close()
    sem = asyncio.Semaphore(20)
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        async def guarded(i):
            async with sem:
                try:
                    await check_site(client, i)
                except Exception:  # noqa: BLE001
                    log.exception("Health check failed for %s", i)
        await asyncio.gather(*(guarded(i) for i in ids))
    return len(ids)


async def check_servers_once() -> int:
    from ..models import Server
    from ..servers import ops

    db = SessionLocal()
    try:
        servers = [(s.id, s.name, s.status) for s in db.scalars(select(Server).where(Server.status.in_(("ok", "ready", "error"))))]
    finally:
        db.close()
    for sid, name, before in servers:
        try:
            m = await ops.refresh_metrics(sid)
            if before == "error":
                _notify_server(sid, f"Server {name} is reachable again", "success", "")
            if m.get("disk_percent", 0) >= 90:
                _notify_server(sid, f"Server {name} disk almost full", "warning", f"{m['disk_percent']}% used")
        except Exception as e:  # noqa: BLE001
            if before != "error":
                _notify_server(sid, f"Server {name} is unreachable", "error", str(e)[:200])
    return len(servers)


def _notify_server(server_id: str, title: str, level: str, message: str) -> None:
    db = SessionLocal()
    try:
        notify(db, website=None, title=title, message=message, level=level, link="/servers")
    finally:
        db.close()


async def monitor_loop() -> None:
    await asyncio.sleep(5)
    while True:
        try:
            await run_checks_once()
            await check_servers_once()
        except Exception:  # noqa: BLE001
            log.exception("Monitor loop error")
        await asyncio.sleep(settings.MONITOR_INTERVAL_SECONDS)
