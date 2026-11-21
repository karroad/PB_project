from __future__ import annotations

from ..models import Approval, Deployment, Job, JobStep, Notification, ProviderAccount, Website
from ..security import decrypt_secret, mask


def iso(dt):
    return dt.isoformat() if dt else None


def website_out(s: Website, detail: bool = False) -> dict:
    cfg = s.config or {}
    brand = cfg.get("brand") or {}
    out = {
        "id": s.id, "name": s.name, "slug": s.slug, "prompt": s.prompt, "stack": s.stack, "stack_selected_by": s.stack_selected_by,
        "status": s.status, "domain": s.domain, "hosting_provider": s.hosting_provider, "dns_provider": s.dns_provider,
        "hosting_account_id": s.hosting_account_id, "dns_account_id": s.dns_account_id, "require_approval": s.require_approval,
        "live_url": s.live_url, "health_status": s.health_status, "last_checked_at": iso(s.last_checked_at),
        "current_deployment_id": s.current_deployment_id, "owner_id": s.owner_id,
        "created_at": iso(s.created_at), "updated_at": iso(s.updated_at),
        "palette": brand.get("palette"), "tagline": brand.get("tagline"),
        "quality_score": (cfg.get("quality") or {}).get("score"),
        "topic": (cfg.get("requirements") or {}).get("topic_title"),
        "domain_mode": cfg.get("domain_mode"),
    }
    if detail:
        out["config"] = {k: v for k, v in cfg.items() if k not in ("fingerprint",)}
        out["env"] = s.env or {}
    return out


def step_out(st: JobStep) -> dict:
    return {"id": st.id, "key": st.key, "name": st.name, "agent": st.agent, "order": st.order, "status": st.status, "progress": st.progress,
            "logs": st.logs or [], "output": st.output or {}, "error": st.error, "attempts": st.attempts,
            "started_at": iso(st.started_at), "finished_at": iso(st.finished_at)}


def job_out(j: Job, steps: bool = False) -> dict:
    out = {"id": j.id, "website_id": j.website_id, "website_name": j.website.name if j.website else None, "type": j.type, "status": j.status,
           "current_step": j.current_step, "progress": j.progress, "error": j.error, "attempts": j.attempts, "worker_id": j.worker_id,
           "created_at": iso(j.created_at), "started_at": iso(j.started_at), "finished_at": iso(j.finished_at), "heartbeat_at": iso(j.heartbeat_at)}
    if steps:
        out["steps"] = [step_out(s) for s in j.steps]
    return out


def deployment_out(d: Deployment) -> dict:
    return {"id": d.id, "version": d.version, "status": d.status, "provider": d.provider, "url": d.url, "quality_score": d.quality_score,
            "job_id": d.job_id, "details": d.details or {}, "created_at": iso(d.created_at)}


def approval_out(a: Approval, site_name: str | None = None) -> dict:
    return {"id": a.id, "job_id": a.job_id, "website_id": a.website_id, "website_name": site_name, "step_key": a.step_key, "action": a.action,
            "description": a.description, "details": a.details or {}, "status": a.status, "requested_at": iso(a.requested_at),
            "decided_by": a.decided_by, "decided_at": iso(a.decided_at)}


def provider_out(p: ProviderAccount, used: int = 0) -> dict:
    creds = decrypt_secret(p.credentials_encrypted)
    return {"id": p.id, "provider": p.provider, "kind": p.kind, "label": p.label, "meta": p.meta or {}, "max_sites": p.max_sites,
            "status": p.status, "used_sites": used, "credentials": {k: mask(str(v)) for k, v in creds.items()}, "created_at": iso(p.created_at)}


def notification_out(n: Notification) -> dict:
    return {"id": n.id, "title": n.title, "message": n.message, "level": n.level, "link": n.link, "read": n.read,
            "website_id": n.website_id, "job_id": n.job_id, "created_at": iso(n.created_at)}
