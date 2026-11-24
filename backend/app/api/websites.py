from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..adapters.dns import DNS, PLANNED_DNS
from ..adapters.hosting import HOSTING, PLANNED_HOSTING, get_hosting
from ..adapters.stacks import STACKS, catalog
from ..agents.pipeline_agents import AGENTS
from ..ai import offline
from ..config import settings
from ..database import get_db
from ..deps import accessible_website_ids, audit, get_current_user, get_website_for_user, require_role
from ..errors import PipelineError
from ..models import Deployment, Domain, FormSubmission, Server, HealthCheck, Job, ProviderAccount, User, Website, WebsiteMember
from ..orchestrator.queue import queue
from ..orchestrator.runner import create_job
from ..schemas import ChangeRequest, DeleteConfirm, PublishRequest, RecommendIn, WebsiteCreate, WebsiteUpdate
from .serializers import deployment_out, job_out, website_out

router = APIRouter(prefix="/api", tags=["websites"])
MAX_WEBSITES = 1000


@router.get("/catalog")
def get_catalog(_: User = Depends(get_current_user)):
    return {
        "stacks": catalog(),
        "hosting": [h.catalog() for h in HOSTING.values()] + PLANNED_HOSTING,
        "dns": [d.catalog() for d in DNS.values()] + PLANNED_DNS,
        "agents": [{"key": a.key, "title": a.title, "agent": a.agent_name, "description": a.description} for a in AGENTS],
        "policy": {"auto_publish": settings.AUTO_PUBLISH, "approval_domain_purchase": settings.APPROVAL_DOMAIN_PURCHASE,
                   "approval_dns_changes": settings.APPROVAL_DNS_CHANGES, "domain_max_price": settings.DOMAIN_MAX_PRICE,
                   "domain_years": settings.DOMAIN_REGISTRATION_YEARS, "domain_auto_renew": settings.DOMAIN_AUTO_RENEW,
                   "public_server": bool(settings.SERVER_PUBLIC_IP) or settings.SANDBOX_PROVIDERS,  # same rule the API enforces
                   "sandbox": settings.SANDBOX_PROVIDERS},
    }


@router.post("/stacks/recommend")
def recommend(body: RecommendIn, _: User = Depends(get_current_user)):
    rec = offline.recommend_stack(body.prompt)
    req = offline.requirements(body.prompt, rec["stack"])
    return {**rec, "site_name": req["site_name"], "topic": req["topic_title"], "theme": req["theme"]}


@router.get("/stats")
def stats(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ids = accessible_website_ids(db, user)
    q = select(Website.status, func.count()).group_by(Website.status)
    jq = select(Job.status, func.count()).group_by(Job.status)
    if ids is not None:
        q, jq = q.where(Website.id.in_(ids)), jq.where(Job.website_id.in_(ids))
    by_status = dict(db.execute(q).all())
    jobs = dict(db.execute(jq).all())
    hq = select(Website.health_status, func.count()).where(Website.status == "live").group_by(Website.health_status)
    if ids is not None:
        hq = hq.where(Website.id.in_(ids))
    return {"websites": sum(by_status.values()), "by_status": by_status, "jobs": jobs, "health": dict(db.execute(hq).all()), "capacity": MAX_WEBSITES}


def _visible(db: Session, user: User):
    q = select(Website)
    ids = accessible_website_ids(db, user)
    return q if ids is None else q.where(Website.id.in_(ids))


@router.get("/websites")
def list_websites(status: str | None = None, q: str | None = None, stack: str | None = None, limit: int = Query(200, le=500), offset: int = 0,
                  db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    query = _visible(db, user)
    if status:
        query = query.where(Website.status == status)
    elif status is None:
        query = query.where(Website.status != "archived")
    if stack:
        query = query.where(Website.stack == stack)
    if q:
        like = f"%{q.lower()}%"
        query = query.where(func.lower(Website.name).like(like) | func.lower(Website.slug).like(like) | func.lower(Website.domain).like(like))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(Website.created_at.desc()).limit(limit).offset(offset)).all()
    return {"total": total, "items": [website_out(s) for s in rows]}


def _unique_slug(db: Session, base: str) -> str:
    slug, i = offline.slugify(base)[:50], 2
    root = slug
    while db.scalar(select(Website.id).where(Website.slug == slug)):
        slug = f"{root}-{i}"
        i += 1
    return slug


def _validate_targets(db: Session, stack: str | None, hosting: str | None, hosting_account: str | None, dns: str | None, dns_account: str | None, domain: str | None):
    if stack is not None:
        if stack == "auto":
            raise HTTPException(422, "Please select a technology — automatic selection is disabled")
        if stack not in STACKS:
            raise HTTPException(422, f"Unknown technology '{stack}'")
        if STACKS[stack].info.status == "planned":
            raise HTTPException(422, f"{STACKS[stack].info.name} is not available yet")
    if hosting is not None:
        if hosting not in HOSTING:
            raise HTTPException(422, f"Unknown or unavailable hosting provider '{hosting}'")
        h = get_hosting(hosting)
        ok, reason = h.enabled()
        if not ok:
            raise HTTPException(422, f"{h.name} is disabled: {reason}")
        if h.external and not hosting_account:
            raise HTTPException(422, f"{h.name} needs a connected provider account")
        if hosting == "hetzner" and not domain:
            raise HTTPException(422, "Hetzner hosting needs a domain")
    if dns is not None and dns not in DNS:
        raise HTTPException(422, f"Unknown domain provider '{dns}'")
    if dns not in (None, "none"):
        if not domain:
            raise HTTPException(422, f"Enter the domain to manage with {DNS[dns].name}")
        if not dns_account:
            raise HTTPException(422, f"Select a connected {DNS[dns].name} account (add one under Providers)")
    for acc_id, expected in ((hosting_account, hosting), (dns_account, dns)):
        if acc_id:
            acc = db.get(ProviderAccount, acc_id)
            if not acc or acc.provider != expected:
                raise HTTPException(422, f"Provider account does not match '{expected}'")


@router.post("/websites", status_code=201)
async def create_website(body: WebsiteCreate, request: Request, db: Session = Depends(get_db), user: User = Depends(require_role("operator"))):
    if (db.scalar(select(func.count()).select_from(Website).where(Website.status != "archived")) or 0) >= MAX_WEBSITES:
        raise HTTPException(409, f"Platform capacity of {MAX_WEBSITES} active websites reached")
    _validate_targets(db, body.stack, body.hosting_provider, body.hosting_account_id, body.dns_provider, body.dns_account_id, body.domain)
    if body.domain and db.scalar(select(Website.id).where(Website.domain == body.domain, Website.status != "archived")):
        raise HTTPException(409, "Another website already uses this domain")

    # Hosting / domain given here are only remembered as defaults for the Publish step: nothing is bought now.
    mode = body.domain_mode if body.dns_provider != "none" else ("existing" if body.domain else None)

    guess = offline.requirements(body.prompt, body.stack)
    name = body.name or guess["site_name"]
    site = Website(name=name, slug=_unique_slug(db, name), prompt=body.prompt.strip(), stack=body.stack,
                   stack_selected_by="user", domain=body.domain, require_approval=body.require_approval or not settings.AUTO_PUBLISH,
                   hosting_provider=body.hosting_provider, hosting_account_id=body.hosting_account_id, dns_provider=body.dns_provider,
                   dns_account_id=body.dns_account_id, owner_id=user.id,
                   config={"name_from_ai": not body.name, "domain_mode": mode,
                           **({"reference_url": body.reference_url} if body.reference_url else {}),
                           **({"contact_phone": body.contact_phone.strip()} if body.contact_phone else {}),
                           **({"contact_email": body.contact_email.strip()} if body.contact_email else {})}, status="draft")
    db.add(site)
    db.commit()
    try:
        job = create_job(db, site, "generate", user)
    except PipelineError as e:
        raise HTTPException(409, e.message)
    await queue.enqueue(job.id)
    audit(db, user, "website.create", "website", site.id, {"prompt": body.prompt[:200], "stack": body.stack, "hosting": body.hosting_provider,
                                                           "domain_provider": body.dns_provider, "domain": body.domain}, request)
    return {"website": website_out(site), "job": job_out(job)}


async def _check_domain_choice(db: Session, site: Website, hosting_key: str, dns: str, dns_account: str | None, domain: str | None,
                               mode: str | None) -> tuple[str | None, dict | None]:
    """Validates a publish target. Returns (domain_mode, quote); quote is set when a domain must be bought."""
    if dns == "none":
        return ("existing" if domain else None), None
    if mode not in ("buy", "existing"):
        raise HTTPException(422, "Choose whether to buy a new domain or use one you already own")
    if mode == "existing":
        return mode, None
    public = bool(settings.SERVER_PUBLIC_IP) or hosting_key in ("hetzner", "server") or settings.SANDBOX_PROVIDERS
    if not public:
        raise HTTPException(422, "A purchased domain must point at a public server: set SERVER_PUBLIC_IP on the backend "
                                 "(or choose Hetzner hosting) before buying domains")
    if settings.DOMAIN_MAX_PRICE <= 0:
        raise HTTPException(422, "Domain purchasing is disabled on this platform (DOMAIN_MAX_PRICE=0)")
    owned = db.scalar(select(Domain).where(Domain.name == domain))
    if owned and owned.website_id != site.id and owned.status != "failed":
        raise HTTPException(409, f"{domain} is already registered for another website")
    if owned and owned.status == "active":
        return mode, None  # already bought for this site: publishing again never buys twice
    from .domains import quote_domains  # local import avoids a cycle
    quote = (await quote_domains(db, dns, dns_account, [domain]))[0]
    if not quote["available"]:
        raise HTTPException(422, f"{domain} can't be registered ({quote.get('reason') or 'unavailable'})")
    if not quote["within_cap"]:
        raise HTTPException(422, f"{domain} costs {quote.get('price')} {quote.get('currency') or ''}, above the {settings.DOMAIN_MAX_PRICE} limit")
    return mode, quote


@router.post("/websites/{website_id}/publish")
async def publish(website_id: str, body: PublishRequest, request: Request, db: Session = Depends(get_db), user: User = Depends(require_role("operator"))):
    """Go live: set up hosting + domain (buy or connect) and deploy the reviewed preview."""
    site = get_website_for_user(db, user, website_id, write=True)
    if site.status == "archived":
        raise HTTPException(409, "Restore the website before publishing")
    if not (site.config or {}).get("preview"):
        raise HTTPException(409, "Build and review the preview before publishing")
    _validate_targets(db, None, body.hosting_provider, body.hosting_account_id, body.dns_provider, body.dns_account_id, body.domain)
    if body.hosting_provider == "server":
        server = db.get(Server, body.server_id) if body.server_id else None
        if not server:
            raise HTTPException(422, "Choose one of your servers")
        if server.status == "error":
            raise HTTPException(422, f"Server {server.name} has a problem: {server.error or 'unreachable'} — fix it under Servers first")
        used = db.scalar(select(func.count()).select_from(Website).where(Website.server_id == server.id, Website.id != site.id, Website.status != "archived")) or 0
        if server.max_sites and used >= server.max_sites:
            raise HTTPException(409, f"Server {server.name} is full ({used}/{server.max_sites} sites)")
        if server.web_server == "traefik" and not body.domain:
            raise HTTPException(422, f"{server.name} serves websites through its existing Traefik, which routes by domain - add a domain")
        if (server.web_config or {}).get("conflict"):
            raise HTTPException(422, f"Ports 80/443 on {server.name} belong to {server.web_server} - SiteForge can't serve websites there")
    if body.domain and db.scalar(select(Website.id).where(Website.domain == body.domain, Website.id != site.id, Website.status != "archived")):
        raise HTTPException(409, "Another website already uses this domain")
    mode, quote = await _check_domain_choice(db, site, body.hosting_provider, body.dns_provider, body.dns_account_id, body.domain, body.domain_mode)

    site.hosting_provider, site.hosting_account_id = body.hosting_provider, body.hosting_account_id
    site.server_id = body.server_id if body.hosting_provider == "server" else None
    site.dns_provider, site.dns_account_id, site.domain = body.dns_provider, body.dns_account_id, body.domain
    site.config = {**(site.config or {}), "domain_mode": mode}
    if quote:  # remember the quoted price; the infrastructure agent re-checks it right before buying
        dom = db.scalar(select(Domain).where(Domain.name == body.domain))
        if dom is None:
            dom = Domain(name=body.domain, provider=body.dns_provider, account_id=body.dns_account_id, website_id=site.id)
            db.add(dom)
        dom.status, dom.price, dom.renewal_price, dom.currency = "quoted", quote.get("price"), quote.get("renewal_price"), quote.get("currency")
        dom.years, dom.auto_renew = settings.DOMAIN_REGISTRATION_YEARS, settings.DOMAIN_AUTO_RENEW
        dom.provider, dom.account_id, dom.website_id = body.dns_provider, body.dns_account_id, site.id
    db.commit()
    try:
        job = create_job(db, site, "publish", user)
    except PipelineError as e:
        raise HTTPException(409, e.message)
    await queue.enqueue(job.id)
    audit(db, user, "website.publish", "website", site.id, {"hosting": body.hosting_provider, "domain_provider": body.dns_provider,
                                                            "domain": body.domain, "domain_mode": mode, "job_id": job.id}, request)
    return job_out(job, steps=True)


@router.get("/websites/{website_id}")
def get_website(website_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    site = get_website_for_user(db, user, website_id)
    latest = db.scalar(select(Job).where(Job.website_id == site.id).order_by(Job.created_at.desc()))
    return {"website": website_out(site, detail=True), "latest_job": job_out(latest, steps=True) if latest else None}


@router.patch("/websites/{website_id}")
def update_website(website_id: str, body: WebsiteUpdate, request: Request, db: Session = Depends(get_db), user: User = Depends(require_role("operator"))):
    site = get_website_for_user(db, user, website_id, write=True)
    changes = body.model_dump(exclude_unset=True)
    _validate_targets(db, None, changes.get("hosting_provider"), changes.get("hosting_account_id", site.hosting_account_id),
                      changes.get("dns_provider"), changes.get("dns_account_id", site.dns_account_id), changes.get("domain", site.domain))
    for k, v in changes.items():
        setattr(site, k, v)
    db.commit()
    audit(db, user, "website.update", "website", site.id, {k: v for k, v in changes.items() if k != "env"}, request)
    return website_out(site, detail=True)


async def _start(db: Session, site: Website, job_type: str, user: User, request: Request) -> dict:
    if site.status == "archived":
        raise HTTPException(409, "Restore the website before running jobs")
    if not (site.config or {}).get("content") and job_type != "generate":
        job_type = "generate"
    try:
        job = create_job(db, site, job_type, user)
    except PipelineError as e:
        raise HTTPException(409, e.message)
    await queue.enqueue(job.id)
    audit(db, user, f"website.{job_type}", "website", site.id, {"job_id": job.id}, request)
    return job_out(job, steps=True)


@router.post("/websites/{website_id}/redeploy")
async def redeploy(website_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(require_role("operator"))):
    return await _start(db, get_website_for_user(db, user, website_id, write=True), "redeploy", user, request)


@router.post("/websites/{website_id}/regenerate")
async def regenerate(website_id: str, request: Request, scope: str = Query("all", pattern="^(all|content)$"),
                     db: Session = Depends(get_db), user: User = Depends(require_role("operator"))):
    site = get_website_for_user(db, user, website_id, write=True)
    return await _start(db, site, "generate" if scope == "all" else "regenerate_content", user, request)


@router.post("/websites/{website_id}/changes")
async def request_changes(website_id: str, body: ChangeRequest, request: Request, db: Session = Depends(get_db), user: User = Depends(require_role("operator"))):
    """A comment on a built website: the Revision Agent applies it, then the site is rebuilt, tested and redeployed."""
    site = get_website_for_user(db, user, website_id, write=True)
    if site.status == "archived":
        raise HTTPException(409, "Restore the website before requesting changes")
    if not (site.config or {}).get("content"):
        raise HTTPException(409, "The website hasn't been generated yet")
    try:
        job = create_job(db, site, "revise", user, params={"instruction": body.instruction.strip()})
    except PipelineError as e:
        raise HTTPException(409, e.message)
    await queue.enqueue(job.id)
    audit(db, user, "website.change_request", "website", site.id, {"job_id": job.id, "instruction": body.instruction[:300]}, request)
    return job_out(job, steps=True)


@router.get("/websites/{website_id}/revisions")
def revisions(website_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    site = get_website_for_user(db, user, website_id)
    from ..agents.revision import EXAMPLES
    from ..ai.llm import get_provider
    revs = list(reversed((site.config or {}).get("revisions", [])))
    return {"ai": not get_provider().offline, "examples": EXAMPLES, "revisions": revs}


@router.post("/websites/{website_id}/restart")
async def restart(website_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(require_role("operator"))):
    site = get_website_for_user(db, user, website_id, write=True)
    dep = db.get(Deployment, site.current_deployment_id) if site.current_deployment_id else None
    if not dep:
        raise HTTPException(409, "No active deployment to restart")
    try:
        msg = await get_hosting(site.hosting_provider).restart(site, dep)
    except PipelineError as e:
        raise HTTPException(502, e.message)
    audit(db, user, "website.restart", "website", site.id, {"result": msg}, request)
    return {"message": msg}


@router.get("/websites/{website_id}/deployments")
def deployments(website_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    site = get_website_for_user(db, user, website_id)
    rows = db.scalars(select(Deployment).where(Deployment.website_id == site.id).order_by(Deployment.version.desc())).all()
    return [deployment_out(d) for d in rows]


@router.post("/websites/{website_id}/rollback/{deployment_id}")
async def rollback(website_id: str, deployment_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(require_role("operator"))):
    site = get_website_for_user(db, user, website_id, write=True)
    target = db.get(Deployment, deployment_id)
    if not target or target.website_id != site.id or target.status == "failed":
        raise HTTPException(404, "Deployment not found or not eligible for rollback")
    if target.provider in ("local", "docker") and target.artifact_path and not Path(target.artifact_path).exists():
        raise HTTPException(410, "Artefact for this deployment no longer exists")
    try:
        await get_hosting(site.hosting_provider).activate(site, target)
    except PipelineError as e:
        raise HTTPException(502, e.message)
    for d in db.scalars(select(Deployment).where(Deployment.website_id == site.id, Deployment.status == "active")):
        d.status = "rolled_back" if d.version > target.version else "superseded"
    target.status = "active"
    site.current_deployment_id, site.live_url, site.status = target.id, target.url, "live"
    db.commit()
    audit(db, user, "website.rollback", "website", site.id, {"to_version": target.version}, request)
    return deployment_out(target)


@router.get("/websites/{website_id}/jobs")
def website_jobs(website_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    site = get_website_for_user(db, user, website_id)
    return [job_out(j) for j in db.scalars(select(Job).where(Job.website_id == site.id).order_by(Job.created_at.desc()).limit(50))]


@router.get("/websites/{website_id}/health")
def health_history(website_id: str, limit: int = Query(120, le=1000), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    site = get_website_for_user(db, user, website_id)
    rows = db.scalars(select(HealthCheck).where(HealthCheck.website_id == site.id).order_by(HealthCheck.checked_at.desc()).limit(limit)).all()
    up = sum(r.ok for r in rows)
    return {"uptime_percent": round(100 * up / len(rows), 2) if rows else None, "monitoring": (site.config or {}).get("monitoring", {}),
            "checks": [{"checked_at": r.checked_at.isoformat(), "ok": r.ok, "status_code": r.status_code, "response_ms": r.response_ms, "error": r.error} for r in reversed(rows)]}


@router.get("/websites/{website_id}/files")
def source_files(website_id: str, path: str | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    site = get_website_for_user(db, user, website_id)
    root = (settings.sites_dir / site.slug / "source").resolve()
    if not root.exists():
        return {"files": []}
    if path is None:
        files = sorted(str(p.relative_to(root)).replace("\\", "/") for p in root.rglob("*") if p.is_file() and "media" not in p.parts)
        return {"files": files[:500]}
    target = (root / path).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise HTTPException(404, "File not found")
    if target.stat().st_size > 300_000:
        raise HTTPException(413, "File too large to preview")
    return {"path": path, "content": target.read_text(encoding="utf-8", errors="replace")}


@router.get("/websites/{website_id}/submissions")
def submissions(website_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    site = get_website_for_user(db, user, website_id)
    rows = db.scalars(select(FormSubmission).where(FormSubmission.website_id == site.id).order_by(FormSubmission.created_at.desc()).limit(200))
    return [{"id": r.id, "data": r.data, "created_at": r.created_at.isoformat()} for r in rows]


@router.post("/websites/{website_id}/members")
def add_member(website_id: str, body: dict, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    site = get_website_for_user(db, user, website_id)
    target = db.scalar(select(User).where(User.email == str(body.get("email", "")).lower()))
    if not target:
        raise HTTPException(404, "User not found")
    role = body.get("role", "editor")
    if role not in ("editor", "viewer"):
        raise HTTPException(422, "role must be editor or viewer")
    m = db.scalar(select(WebsiteMember).where(WebsiteMember.website_id == site.id, WebsiteMember.user_id == target.id)) or WebsiteMember(website_id=site.id, user_id=target.id)
    m.role = role
    db.add(m)
    db.commit()
    audit(db, user, "website.member_add", "website", site.id, {"user": target.email, "role": role})
    return {"ok": True}


@router.post("/websites/{website_id}/archive")
def archive(website_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(require_role("operator"))):
    site = get_website_for_user(db, user, website_id, write=True)
    if db.scalar(select(Job).where(Job.website_id == site.id, Job.status.in_(("queued", "running")))):
        raise HTTPException(409, "Cancel the running job first")
    site.config = {**(site.config or {}), "status_before_archive": site.status}
    site.status = "archived"
    db.commit()
    audit(db, user, "website.archive", "website", site.id, request=request)
    return website_out(site)


@router.post("/websites/{website_id}/restore")
def restore(website_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(require_role("operator"))):
    site = get_website_for_user(db, user, website_id, write=True)
    if site.status != "archived":
        raise HTTPException(409, "Website is not archived")
    fallback = "live" if site.current_deployment_id else ("preview" if (site.config or {}).get("preview") else "draft")
    site.status = (site.config or {}).get("status_before_archive", fallback)
    db.commit()
    audit(db, user, "website.restore", "website", site.id, request=request)
    return website_out(site)


@router.delete("/websites/{website_id}")
async def delete_website(website_id: str, body: DeleteConfirm, request: Request, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    site = get_website_for_user(db, user, website_id, write=True)
    if body.confirm != site.slug:
        raise HTTPException(400, f"Type the website slug '{site.slug}' to confirm deletion")
    if db.scalar(select(Job).where(Job.website_id == site.id, Job.status.in_(("queued", "running")))):
        raise HTTPException(409, "Cancel the running job first")
    if site.hosting_provider == "docker":
        import asyncio

        proc = await asyncio.create_subprocess_exec("docker", "compose", "-p", f"sf-{site.slug}", "down", stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await proc.wait()
    if site.hosting_provider == "server" and site.server_id:
        from ..servers.ops import remove_site
        try:
            await remove_site(site.server_id, site.slug)
        except PipelineError as e:
            raise HTTPException(502, f"Couldn't remove the site from its server: {e.message}")
    slug, sid = site.slug, site.id
    db.delete(site)
    db.commit()
    for d in (settings.sites_dir / slug, settings.deployments_dir / slug):
        shutil.rmtree(d, ignore_errors=True)
    audit(db, user, "website.delete", "website", sid, {"slug": slug}, request)
    return {"deleted": True}
