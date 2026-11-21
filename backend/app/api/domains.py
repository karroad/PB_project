"""Domain search (live price + availability from Cloudflare / OVH) and the purchased-domain registry."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..adapters.dns import DNS, domain_candidates, rdap_lookup
from ..config import settings
from ..database import get_db
from ..deps import accessible_website_ids, audit, get_current_user, require_role
from ..errors import PipelineError
from ..models import Domain, ProviderAccount, User, Website, utcnow
from ..security import decrypt_secret

router = APIRouter(prefix="/api/domains", tags=["domains"])


def provider_creds(db: Session, provider: str, account_id: str | None) -> dict:
    if not account_id:
        raise HTTPException(422, f"Select a connected {DNS[provider].name} account")
    acc = db.get(ProviderAccount, account_id)
    if not acc or acc.provider != provider:
        raise HTTPException(422, f"Account does not belong to {DNS[provider].name}")
    return {**(acc.meta or {}), **decrypt_secret(acc.credentials_encrypted)}


async def quote_domains(db: Session, provider: str, account_id: str | None, domains: list[str]) -> list[dict]:
    adapter = DNS.get(provider)
    if not adapter or not adapter.can_register:
        raise HTTPException(422, f"'{provider}' cannot register domains")
    creds = provider_creds(db, provider, account_id)
    try:
        results = await adapter.check_domains(creds, domains)
    except PipelineError as e:
        raise HTTPException(502, e.message)
    except Exception as e:  # provider/network failure
        raise HTTPException(502, f"{adapter.name} could not be reached: {e.__class__.__name__}: {str(e)[:200]}")
    taken = {d.name for d in db.scalars(select(Domain).where(Domain.name.in_([r["domain"] for r in results]), Domain.status != "failed"))}
    for r in results:
        r["within_cap"] = r.get("price") is not None and r["price"] <= settings.DOMAIN_MAX_PRICE
        r["in_use"] = r["domain"] in taken
        r["buyable"] = bool(r["available"] and r["within_cap"] and not r["in_use"])
    return results


@router.get("/check")
async def check_domain(domain: str = Query(min_length=4), _: User = Depends(get_current_user)):
    return await rdap_lookup(domain.strip().lower())


@router.get("/search")
async def search(q: str = Query(min_length=2, max_length=80), provider: str = Query(...), account_id: str | None = None,
                 db: Session = Depends(get_db), _: User = Depends(require_role("operator"))):
    results = await quote_domains(db, provider, account_id, domain_candidates(q))
    return {"max_price": settings.DOMAIN_MAX_PRICE, "years": settings.DOMAIN_REGISTRATION_YEARS,
            "approval_required": settings.APPROVAL_DOMAIN_PURCHASE, "results": results}


def _out(d: Domain, site_name: str | None) -> dict:
    return {"id": d.id, "name": d.name, "provider": d.provider, "status": d.status, "price": d.price, "renewal_price": d.renewal_price,
            "currency": d.currency, "years": d.years, "auto_renew": d.auto_renew, "expires_at": d.expires_at, "error": d.error,
            "order_ref": d.order_ref, "website_id": d.website_id, "website_name": site_name, "created_at": d.created_at.isoformat(),
            "updated_at": d.updated_at.isoformat() if d.updated_at else None}


@router.get("")
def list_domains(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = select(Domain, Website.name).outerjoin(Website, Website.id == Domain.website_id).order_by(Domain.created_at.desc())
    ids = accessible_website_ids(db, user)
    if ids is not None:
        q = q.where(Domain.website_id.in_(ids))
    return [_out(d, n) for d, n in db.execute(q)]


@router.post("/{domain_id}/sync")
async def sync(domain_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(require_role("operator"))):
    """Ask the provider for the real state of an order (e.g. after an interrupted purchase)."""
    d = db.get(Domain, domain_id)
    if not d:
        raise HTTPException(404, "Domain not found")
    creds = provider_creds(db, d.provider, d.account_id)
    try:
        st = await DNS[d.provider].registration_status(creds, d.name, d.order_ref)
    except Exception as e:
        raise HTTPException(502, f"Provider check failed: {e.__class__.__name__}: {str(e)[:200]}")
    if st["status"] == "active":
        d.status, d.error, d.expires_at = "active", None, st.get("expires_at") or d.expires_at
    elif st["status"] == "failed":
        d.status, d.error = "failed", st.get("message")
    elif d.status == "unknown" and st["status"] == "pending" and d.order_ref:
        d.status = "pending"
    d.updated_at = utcnow()
    db.commit()
    audit(db, user, "domain.sync", "domain", d.id, {"name": d.name, "result": st}, request)
    return _out(d, None)


@router.post("/{domain_id}/reset")
def reset(domain_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    """Admin confirms an interrupted order was NOT placed, so the purchase may be attempted again."""
    d = db.get(Domain, domain_id)
    if not d:
        raise HTTPException(404, "Domain not found")
    if d.status not in ("unknown", "failed"):
        raise HTTPException(409, f"Only unknown or failed purchases can be reset (status: {d.status})")
    d.status, d.error, d.order_ref = "quoted", None, None
    db.commit()
    audit(db, user, "domain.reset", "domain", d.id, {"name": d.name}, request)
    return _out(d, None)
