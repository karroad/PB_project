"""Approvals, provider accounts, notifications, monitoring and audit endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from ..adapters.dns import DNS
from ..adapters.hosting import HOSTING
from ..config import settings
from ..ai.llm import get_provider
from ..database import get_db
from ..deps import accessible_website_ids, audit, get_current_user, get_website_for_user, require_role
from ..events import bus
from ..models import Approval, AuditLog, Job, Notification, ProviderAccount, User, Website, utcnow
from ..monitoring.monitor import run_checks_once, system_stats
from ..orchestrator.queue import queue
from ..schemas import DecisionIn, ProviderCreate
from ..security import decrypt_secret, encrypt_secret
from .serializers import approval_out, notification_out, provider_out

router = APIRouter(prefix="/api", tags=["platform"])


# ---------------------------------------------------------------- approvals
@router.get("/approvals")
def list_approvals(status: str = "pending", db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = select(Approval, Website.name).join(Website, Website.id == Approval.website_id).order_by(Approval.requested_at.desc()).limit(200)
    if status != "all":
        q = q.where(Approval.status == status)
    ids = accessible_website_ids(db, user)
    if ids is not None:
        q = q.where(Approval.website_id.in_(ids))
    return [approval_out(a, name) for a, name in db.execute(q)]


async def _decide(approval_id: str, decision: str, body: DecisionIn, request: Request, db: Session, user: User):
    a = db.get(Approval, approval_id)
    if not a:
        raise HTTPException(404, "Approval not found")
    get_website_for_user(db, user, a.website_id, write=True)
    if a.status != "pending":
        raise HTTPException(409, f"Already {a.status}")
    if a.action in ("provision_hosting", "configure_dns", "register_domain") and user.role != "admin":
        raise HTTPException(403, "Only admins can approve infrastructure or external account changes")
    a.status, a.decided_by, a.decided_at = decision, user.id, utcnow()
    a.details = {**(a.details or {}), "comment": body.comment}
    job = db.get(Job, a.job_id)
    if job and job.status == "awaiting_approval":
        job.status = "queued"  # resume: approved continues, rejected fails cleanly inside the step
    db.commit()
    audit(db, user, f"approval.{decision}", "approval", a.id, {"action": a.action, "job_id": a.job_id}, request)
    bus.publish(f"job:{a.job_id}", {"type": f"approval_{decision}", "job_id": a.job_id, "website_id": a.website_id,
                                     "step": a.step_key, "message": f"{a.action} {decision} by {user.email}"})
    if job and job.status == "queued":
        await queue.enqueue(job.id)
    return approval_out(a)


@router.post("/approvals/{approval_id}/approve")
async def approve(approval_id: str, request: Request, body: DecisionIn = DecisionIn(), db: Session = Depends(get_db), user: User = Depends(require_role("operator"))):
    return await _decide(approval_id, "approved", body, request, db, user)


@router.post("/approvals/{approval_id}/reject")
async def reject(approval_id: str, request: Request, body: DecisionIn = DecisionIn(), db: Session = Depends(get_db), user: User = Depends(require_role("operator"))):
    return await _decide(approval_id, "rejected", body, request, db, user)


# ---------------------------------------------------------------- providers
PROVIDER_CATALOG = {
    **{k: {"kind": "hosting", **h.catalog()} for k, h in HOSTING.items() if h.external},
    **{k: {"kind": "dns", **d.catalog()} for k, d in DNS.items() if k != "none"},
    "fal": {"kind": "ai", "key": "fal", "name": "Fal.ai", "description": "Image generation", "credential_fields": ["api_key"], "enabled": True},
}


def _usage(db: Session, acc_id: str) -> int:
    return db.scalar(select(func.count()).select_from(Website).where(
        or_(Website.hosting_account_id == acc_id, Website.dns_account_id == acc_id), Website.status != "archived")) or 0


@router.get("/providers/catalog")
def providers_catalog(_: User = Depends(get_current_user)):
    return list(PROVIDER_CATALOG.values())


@router.get("/providers")
def list_providers(db: Session = Depends(get_db), _: User = Depends(require_role("operator"))):
    return [provider_out(p, _usage(db, p.id)) for p in db.scalars(select(ProviderAccount).order_by(ProviderAccount.created_at))]


@router.post("/providers", status_code=201)
def create_provider(body: ProviderCreate, request: Request, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    if body.provider not in PROVIDER_CATALOG:
        raise HTTPException(422, f"Unsupported provider '{body.provider}'")
    acc = ProviderAccount(provider=body.provider, kind=PROVIDER_CATALOG[body.provider]["kind"], label=body.label,
                          credentials_encrypted=encrypt_secret({k: v for k, v in body.credentials.items() if v}), meta=body.meta, max_sites=body.max_sites)
    db.add(acc)
    db.commit()
    audit(db, user, "provider.create", "provider", acc.id, {"provider": acc.provider, "label": acc.label}, request)
    return provider_out(acc)


@router.post("/providers/{provider_id}/test")
async def test_provider(provider_id: str, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    acc = db.get(ProviderAccount, provider_id)
    if not acc:
        raise HTTPException(404, "Provider account not found")
    creds = {**(acc.meta or {}), **decrypt_secret(acc.credentials_encrypted)}
    adapter = HOSTING.get(acc.provider) or DNS.get(acc.provider)
    ok, msg = (await adapter.test_credentials(creds)) if adapter else (bool(creds.get("api_key")), "Key stored" if creds.get("api_key") else "Missing api_key")
    acc.status = "ok" if ok else "error"
    db.commit()
    audit(db, user, "provider.test", "provider", acc.id, {"ok": ok})
    return {"ok": ok, "message": msg}


@router.delete("/providers/{provider_id}")
def delete_provider(provider_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    acc = db.get(ProviderAccount, provider_id)
    if not acc:
        raise HTTPException(404, "Provider account not found")
    if _usage(db, acc.id):
        raise HTTPException(409, "Account is attached to websites — detach them first")
    db.delete(acc)
    db.commit()
    audit(db, user, "provider.delete", "provider", provider_id, {"provider": acc.provider}, request)
    return {"deleted": True}


# ---------------------------------------------------------------- notifications
@router.get("/notifications")
def list_notifications(unread: bool = False, limit: int = Query(50, le=200), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = select(Notification).where(Notification.user_id == user.id).order_by(Notification.created_at.desc()).limit(limit)
    if unread:
        q = q.where(Notification.read.is_(False))
    count = db.scalar(select(func.count()).select_from(Notification).where(Notification.user_id == user.id, Notification.read.is_(False)))
    return {"unread": count, "items": [notification_out(n) for n in db.scalars(q)]}


@router.post("/notifications/read")
def mark_read(body: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = update(Notification).where(Notification.user_id == user.id)
    if body.get("ids"):
        q = q.where(Notification.id.in_(body["ids"]))
    db.execute(q.values(read=True))
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- monitoring & audit
@router.get("/monitoring/overview")
async def monitoring_overview(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ids = accessible_website_ids(db, user)
    q = select(Website).where(Website.status == "live")
    if ids is not None:
        q = q.where(Website.id.in_(ids))
    sites = [{"id": s.id, "name": s.name, "slug": s.slug, "url": s.live_url, "health": s.health_status, "hosting": s.hosting_provider,
              "last_checked_at": s.last_checked_at.isoformat() if s.last_checked_at else None, "monitoring": (s.config or {}).get("monitoring", {}),
              "quality": (s.config or {}).get("quality", {}).get("score")} for s in db.scalars(q)]
    failed_jobs = db.scalar(select(func.count()).select_from(Job).where(Job.status == "failed")) or 0
    return {"system": system_stats(), "queue": await queue.stats(), "ai_provider": get_provider().name,
            "image_provider": "fal" if settings.FAL_KEY or db.scalar(select(ProviderAccount.id).where(ProviderAccount.provider == "fal")) else "svg-fallback",
            "event_bus": bus.__class__.__name__, "failed_jobs": failed_jobs, "sites": sites}


@router.post("/monitoring/check-now")
async def check_now(_: User = Depends(require_role("operator"))):
    return {"checked": await run_checks_once()}


@router.get("/audit")
def audit_logs(limit: int = Query(200, le=1000), action: str | None = None, db: Session = Depends(get_db), _: User = Depends(require_role("admin"))):
    q = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    if action:
        q = q.where(AuditLog.action.like(f"{action}%"))
    return [{"id": a.id, "user_email": a.user_email, "action": a.action, "target_type": a.target_type, "target_id": a.target_id,
             "details": a.details, "ip": a.ip, "created_at": a.created_at.isoformat()} for a in db.scalars(q)]
