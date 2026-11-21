"""Persists everything a running job does and broadcasts it live.

Every log line, progress change, step transition and error is written to the database
(JobStep + append-only JobEvent) *before* being published, so the dashboard can always
rebuild the full history and clients that reconnect can replay what they missed.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from ..errors import ConfigurationError
from ..events import bus
from ..models import Deployment, Domain, Job, JobEvent, JobStep, ProviderAccount, Website, utcnow
from ..security import decrypt_secret

MAX_STEP_LOGS = 300


class Recorder:
    def __init__(self, db: Session, job: Job, site: Website) -> None:
        self.db, self.job, self.site = db, job, site
        self._steps = {s.key: s for s in job.steps}

    # ------------------------------------------------------------------ events
    def emit(self, type_: str, step_key: str | None = None, message: str = "", level: str = "info", data: dict | None = None) -> dict:
        ev = JobEvent(job_id=self.job.id, website_id=self.site.id, step_key=step_key, type=type_, level=level, message=message, data=data or {})
        self.db.add(ev)
        self.job.heartbeat_at = utcnow()
        self.db.commit()
        payload = {"id": ev.id, "type": type_, "job_id": self.job.id, "website_id": self.site.id, "step": step_key,
                   "level": level, "message": message, "data": data or {}, "progress": self.job.progress, "ts": ev.created_at.isoformat()}
        bus.publish(f"job:{self.job.id}", payload)
        return payload

    def step(self, key: str) -> JobStep:
        return self._steps[key]

    async def log(self, step_key: str, message: str, level: str = "info", progress: float | None = None, data: dict | None = None) -> None:
        st = self.step(step_key)
        entry = {"ts": utcnow().isoformat(), "level": level, "message": message}
        st.logs = (list(st.logs or []) + [entry])[-MAX_STEP_LOGS:]
        if progress is not None:
            st.progress = max(st.progress or 0, min(100.0, float(progress)))
            self._recalc_job_progress()
        self.emit("log", step_key, message, level, {"step_progress": st.progress, **(data or {})})

    async def progress(self, step_key: str, pct: float) -> None:
        st = self.step(step_key)
        st.progress = min(100.0, float(pct))
        self._recalc_job_progress()
        self.emit("progress", step_key, "", "info", {"step_progress": st.progress})

    def _recalc_job_progress(self) -> None:
        steps = list(self._steps.values())
        total = sum(100 if s.status in ("completed", "skipped") else (s.progress or 0) for s in steps)
        self.job.progress = round(total / max(1, len(steps)), 1)

    # ------------------------------------------------------------------ credentials
    def credentials(self, account_id: str | None) -> dict:
        if not account_id:
            return {}
        acc = self.db.get(ProviderAccount, account_id)
        if not acc:
            raise ConfigurationError("Attached provider account no longer exists", hint="Re-attach a provider account to this website.")
        return {**(acc.meta or {}), **decrypt_secret(acc.credentials_encrypted)}

    def provider_secret(self, provider: str, field: str) -> str | None:
        acc = self.db.scalar(select(ProviderAccount).where(ProviderAccount.provider == provider).order_by(ProviderAccount.created_at))
        return decrypt_secret(acc.credentials_encrypted).get(field) if acc else None

    def all_secret_values(self) -> list[str]:
        from ..config import settings

        values = [settings.ANTHROPIC_API_KEY, settings.FAL_KEY, settings.SECRET_KEY]
        for acc in self.db.scalars(select(ProviderAccount)):
            values += [str(v) for v in decrypt_secret(acc.credentials_encrypted).values()]
        return [v for v in values if v and len(v) >= 8]

    def account_usage(self, account_id: str) -> tuple[int, int | None]:
        acc = self.db.get(ProviderAccount, account_id)
        used = self.db.scalar(select(func.count()).select_from(Website).where(
            (Website.hosting_account_id == account_id) | (Website.dns_account_id == account_id), Website.status != "archived")) or 0
        return used, acc.max_sites if acc else None

    def other_fingerprints(self) -> dict[str, set]:
        out = {}
        for slug, cfg in self.db.execute(select(Website.slug, Website.config).where(Website.id != self.site.id)):
            fp = (cfg or {}).get("fingerprint")
            if fp:
                out[slug] = set(fp)
        return out

    # ------------------------------------------------------------------ domains
    def get_domain(self, name: str) -> Domain | None:
        return self.db.scalar(select(Domain).where(Domain.name == name))

    def save_domain(self, dom: Domain | None, **fields) -> Domain:
        """Create or update a domain row and commit immediately (purchase state must never be lost)."""
        if dom is None:
            dom = Domain(**fields)
            self.db.add(dom)
        else:
            for k, v in fields.items():
                setattr(dom, k, v)
        self.db.commit()
        self.emit("domain", None, f"{dom.name}: {dom.status}", "info", {"domain": dom.name, "status": dom.status})
        return dom

    # ------------------------------------------------------------------ deployments
    def next_version(self) -> int:
        return (self.db.scalar(select(func.max(Deployment.version)).where(Deployment.website_id == self.site.id)) or 0) + 1

    def create_deployment(self, version: int, provider: str, result: dict, score: float | None) -> str:
        dep = Deployment(website_id=self.site.id, job_id=self.job.id, version=version, status="verifying", provider=provider,
                         artifact_path=result.get("artifact_path"), url=result.get("url"), quality_score=score, details=result.get("details", {}))
        self.db.add(dep)
        self.db.commit()
        return dep.id

    def switch_traffic(self, dep_id: str) -> None:
        self.site.current_deployment_id = dep_id
        self.db.commit()

    def rollback_traffic(self, previous_id: str | None) -> str | None:
        current = self.db.get(Deployment, self.site.current_deployment_id) if self.site.current_deployment_id else None
        if current and current.status == "verifying":
            current.status = "failed"
        prev = self.db.get(Deployment, previous_id) if previous_id else None
        self.site.current_deployment_id = prev.id if prev else None
        self.db.commit()
        if prev:
            self.emit("rollback", "verify", f"Rolled back to v{prev.version}", "warning")
            return f"v{prev.version}"
        return None

    def mark_live(self, dep_id: str, url: str, verification: dict) -> None:
        for d in self.db.scalars(select(Deployment).where(Deployment.website_id == self.site.id, Deployment.status == "active")):
            d.status = "superseded"
        dep = self.db.get(Deployment, dep_id)
        dep.status = "active"
        dep.details = {**(dep.details or {}), "verification": verification}
        flag_modified(dep, "details")
        self.site.current_deployment_id = dep_id
        self.site.live_url = url
        self.site.status = "live"
        self.site.health_status = "up" if verification.get("status") == 200 or not verification.get("checked") else "degraded"
        self.site.last_checked_at = utcnow()
        self.db.commit()
