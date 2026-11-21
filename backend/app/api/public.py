"""Public endpoints: serving locally hosted sites, media previews and contact forms."""
from __future__ import annotations

import re
import time
from collections import defaultdict, deque
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import select

from ..config import settings
from ..database import SessionLocal
from ..models import Deployment, FormSubmission, Website

router = APIRouter(tags=["public"])
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                               "font-src https://fonts.gstatic.com; script-src 'self' 'unsafe-inline'; form-action 'self' " + settings.PUBLIC_BASE_URL
                               + "; frame-ancestors 'self' " + settings.FRONTEND_ORIGIN,
}
_SAFE = re.compile(r"^[a-zA-Z0-9._-]+$")
_form_hits: dict[str, deque] = defaultdict(deque)


def _with_headers(resp, cache: str = "public, max-age=60"):
    for k, v in SECURITY_HEADERS.items():
        resp.headers[k] = v
    resp.headers["Cache-Control"] = cache
    return resp


@router.get("/api/media/{slug}/{filename}")
def media(slug: str, filename: str):
    if not _SAFE.match(slug) or not _SAFE.match(filename):
        raise HTTPException(404)
    p = settings.sites_dir / slug / "media" / filename
    if not p.is_file():
        raise HTTPException(404)
    return _with_headers(FileResponse(p), "public, max-age=3600")


@router.get("/sites/{slug}")
def site_root(slug: str):
    return RedirectResponse(f"/sites/{slug}/", status_code=308)


@router.get("/sites/{slug}/{path:path}")
def serve_site(slug: str, path: str = ""):
    db = SessionLocal()
    try:
        site = db.scalar(select(Website).where(Website.slug == slug))
        if not site or not site.current_deployment_id:
            raise HTTPException(404, "Site not found")
        if site.status == "archived":
            raise HTTPException(410, "This website has been archived")
        dep = db.get(Deployment, site.current_deployment_id)
    finally:
        db.close()
    if not dep or not dep.artifact_path:
        raise HTTPException(404)
    root = Path(dep.artifact_path).resolve()
    target = (root / path).resolve()
    if not target.is_relative_to(root):
        raise HTTPException(404)
    if target.is_dir():
        if path and not path.endswith("/"):
            # relative redirect works both under /sites/<slug>/ and on the site's own domain
            return RedirectResponse(path.rstrip("/").split("/")[-1] + "/", status_code=308)
        target = target / "index.html"
    if not target.is_file():
        nf = root / "404.html"
        if nf.is_file():
            return _with_headers(FileResponse(nf, status_code=404), "no-cache")
        raise HTTPException(404)
    cache = "no-cache" if target.suffix == ".html" else "public, max-age=86400"
    return _with_headers(FileResponse(target), cache)


@router.get("/preview/{slug}")
def preview_root(slug: str):
    return RedirectResponse(f"/preview/{slug}/", status_code=308)


@router.get("/preview/{slug}/{path:path}")
def serve_preview(slug: str, path: str = ""):
    """The reviewed-but-unpublished build. Never indexed by search engines."""
    if not _SAFE.match(slug):
        raise HTTPException(404)
    root = (settings.sites_dir / slug / "preview").resolve()
    if not root.is_dir():
        raise HTTPException(404, "No preview for this website yet")
    target = (root / path).resolve()
    if not target.is_relative_to(root):
        raise HTTPException(404)
    if target.is_dir():
        if path and not path.endswith("/"):
            return RedirectResponse(path.rstrip("/").split("/")[-1] + "/", status_code=308)
        target = target / "index.html"
    if target.is_file():
        resp = FileResponse(target)
    elif (root / "404.html").is_file():
        resp = FileResponse(root / "404.html", status_code=404)
    else:
        raise HTTPException(404)
    resp = _with_headers(resp, "no-store")
    resp.headers["X-Robots-Tag"] = "noindex, nofollow"
    return resp


_domain_cache: dict[str, tuple[float, str | None]] = {}


def slug_for_host(host: str) -> str | None:
    """Maps a custom domain (Host header) to a locally hosted site's slug, cached for 30s."""
    now = time.time()
    hit = _domain_cache.get(host)
    if hit and now - hit[0] < 30:
        return hit[1]
    db = SessionLocal()
    try:
        slug = db.scalar(select(Website.slug).where(Website.domain == host, Website.hosting_provider == "local", Website.status != "archived"))
    finally:
        db.close()
    _domain_cache[host] = (now, slug)
    return slug


@router.post("/api/public/forms/{slug}")
async def submit_form(slug: str, request: Request):
    ip = request.client.host if request.client else "?"
    hits = _form_hits[ip]
    now = time.time()
    while hits and now - hits[0] > 600:
        hits.popleft()
    if len(hits) >= 10:
        raise HTTPException(429, "Too many submissions")
    hits.append(now)
    form = await request.form()
    db = SessionLocal()
    try:
        site = db.scalar(select(Website).where(Website.slug == slug))
        if not site:
            raise HTTPException(404)
        base = site.live_url or ((site.config or {}).get("preview") or {}).get("url") or f"/sites/{slug}/"
        redirect = base + "contact/thanks/"
        if form.get("_hp"):  # honeypot: silently accept bots
            return RedirectResponse(redirect, status_code=303)
        data = {k: str(v)[:4000] for k, v in form.items() if k in ("name", "email", "message")}
        if not data.get("email") or not data.get("message"):
            raise HTTPException(422, "Email and message are required")
        db.add(FormSubmission(website_id=site.id, data={**data, "ip": ip}))
        db.commit()
    finally:
        db.close()
    return RedirectResponse(redirect, status_code=303)
