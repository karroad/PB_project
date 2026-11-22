"""Orchestrator: runs a job's steps in order with retries, approval gates, cancellation,
timeouts, resumability and full persistence of every transition."""
from __future__ import annotations

import asyncio
import logging
import random
import traceback
from collections import defaultdict

from sqlalchemy import select, update
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from ..agents.base import SiteInfo, StepContext
from ..agents.pipeline_agents import AGENT_BY_KEY, JOB_TYPES, PREVIEW_JOBS
from ..config import settings
from ..database import SessionLocal
from ..errors import ApprovalRequired, JobCancelled, PipelineError, classify
from ..models import Approval, Job, JobStep, User, Website, utcnow
from ..notify import notify
from .recorder import Recorder

log = logging.getLogger("siteforge.orchestrator")
INFRA_STEPS = {"infrastructure", "deployment"}
_provider_locks: dict[str, asyncio.Semaphore] = defaultdict(lambda: asyncio.Semaphore(settings.PROVIDER_CONCURRENCY))


def create_job(db: Session, site: Website, job_type: str, user: User | None, params: dict | None = None) -> Job:
    if job_type not in JOB_TYPES:
        raise ValueError(f"Unknown job type {job_type}")
    active = db.scalar(select(Job).where(Job.website_id == site.id, Job.status.in_(("queued", "running", "awaiting_approval"))))
    if active:
        raise PipelineError("This website already has an active job", code="job_conflict", details={"job_id": active.id})
    job = Job(website_id=site.id, type=job_type, status="queued", created_by=user.id if user else None, params=params)
    for i, key in enumerate(JOB_TYPES[job_type]):
        a = AGENT_BY_KEY[key]
        job.steps.append(JobStep(key=key, name=a.title, agent=a.agent_name, order=i))
    db.add(job)
    if site.status != "live":
        site.status = "generating"
    db.commit()
    return job


def _claim(db: Session, job_id: str, worker_id: str) -> bool:
    """Atomic claim so a job runs on exactly one worker even with many processes."""
    res = db.execute(update(Job).where(Job.id == job_id, Job.status == "queued")
                     .values(status="running", worker_id=worker_id, heartbeat_at=utcnow()))
    db.commit()
    return res.rowcount == 1


def _site_info(site: Website) -> SiteInfo:
    return SiteInfo(id=site.id, slug=site.slug, name=site.name, prompt=site.prompt, stack=site.stack, domain=site.domain,
                    hosting_provider=site.hosting_provider, hosting_account_id=site.hosting_account_id, dns_provider=site.dns_provider,
                    dns_account_id=site.dns_account_id, require_approval=site.require_approval, current_deployment_id=site.current_deployment_id,
                    status=site.status, server_id=site.server_id)


async def run_job(job_id: str, worker_id: str = "embedded") -> None:
    db = SessionLocal()
    try:
        if not _claim(db, job_id, worker_id):
            return
        job = db.get(Job, job_id)
        site = job.website
        rec = Recorder(db, job, site)
        job.attempts += 1
        job.error = None
        job.started_at = job.started_at or utcnow()
        if site.status not in ("live", "archived"):
            site.status = "generating"
        db.commit()
        first = job.attempts == 1 and all(s.status == "pending" for s in job.steps)
        rec.emit("job_started" if first else "job_resumed", None, f"{'Started' if first else 'Resumed'} {job.type} job (attempt {job.attempts})")
        if first:
            what = {"generate": "Generation started", "revise": "Applying changes", "publish": "Publishing", "redeploy": "Redeploying"}.get(job.type, "Job started")
            detail = (job.params or {}).get("instruction") or site.prompt
            notify(db, website=site, job_id=job.id, title=f"{what}: {site.name}", message=detail[:160], level="info")

        approvals = {a.action: a.status for a in db.scalars(select(Approval).where(Approval.job_id == job.id).order_by(Approval.requested_at))}
        try:
            async with asyncio.timeout(settings.JOB_TIMEOUT_SECONDS):
                for step in job.steps:
                    if step.status in ("completed", "skipped"):
                        continue
                    db.refresh(job, ["cancel_requested"])
                    if job.cancel_requested:
                        raise JobCancelled()
                    outcome = await _run_step(db, rec, job, site, step, approvals)
                    if outcome != "ok":
                        return
        except JobCancelled:
            _finish(db, rec, job, site, "cancelled", "Job cancelled by user", level="warning")
            return
        except TimeoutError:
            _finish(db, rec, job, site, "failed", f"Job exceeded {settings.JOB_TIMEOUT_SECONDS}s timeout", level="error")
            return

        job.status, job.progress, job.finished_at, job.current_step = "completed", 100.0, utcnow(), None
        db.commit()
        if job.type in PREVIEW_JOBS:
            url = (site.config or {}).get("preview", {}).get("url", "")
            rec.emit("job_completed", None, f"Preview of {site.name} is ready at {url}", "success", {"url": url, "preview": True})
            notify(db, website=site, job_id=job.id, title=f"👀 Preview ready: {site.name}", message="Review it, request changes, then publish.", level="success")
        else:
            rec.emit("job_completed", None, f"{site.name} is live at {site.live_url}", "success", {"url": site.live_url})
            notify(db, website=site, job_id=job.id, title=f"🚀 {site.name} is live", message=site.live_url or "", level="success")
    except Exception as e:  # last-resort safety net: never leave a job stuck in 'running'
        log.exception("Orchestrator crashed for job %s", job_id)
        try:
            db.rollback()
            job = db.get(Job, job_id)
            if job and job.status == "running":
                job.status, job.error, job.finished_at = "failed", f"Orchestrator error: {e}", utcnow()
                db.commit()
        except Exception:  # noqa: BLE001
            log.exception("Could not mark job %s as failed", job_id)
    finally:
        db.close()


async def _run_step(db: Session, rec: Recorder, job: Job, site: Website, step: JobStep, approvals: dict[str, str]) -> str:
    agent = AGENT_BY_KEY[step.key]
    for attempt in range(settings.STEP_RETRIES + 1):
        step.status, step.error, step.started_at = "running", None, utcnow()
        step.attempts += 1
        job.current_step = step.key
        if attempt == 0:
            step.progress = 0
        db.commit()
        rec.emit("step_started", step.key, f"{agent.agent_name} started: {agent.title}", "info", {"attempt": step.attempts, "agent": agent.agent_name})

        ctx = StepContext(recorder=rec, step_key=step.key, site=_site_info(site), state=dict(site.config or {}), approvals=approvals,
                          params=dict(job.params or {}))
        try:
            coro = agent.run(ctx)
            if step.key in INFRA_STEPS:
                async with _provider_locks[site.hosting_provider]:
                    output = await asyncio.wait_for(coro, timeout=settings.STEP_TIMEOUT_SECONDS)
            else:
                output = await asyncio.wait_for(coro, timeout=settings.STEP_TIMEOUT_SECONDS)
        except ApprovalRequired as a:
            if approvals.get(a.action) == "rejected":
                return _fail_step(db, rec, job, site, step, PipelineError(f"Approval rejected: {a.description}", code="approval_rejected",
                                                                          hint="Change the configuration and start a new job."), None)
            _persist_state(db, site, ctx)
            pending = db.scalar(select(Approval).where(Approval.job_id == job.id, Approval.action == a.action, Approval.status == "pending"))
            if not pending:
                pending = Approval(job_id=job.id, website_id=site.id, step_key=step.key, action=a.action, description=a.description, details=a.details)
                db.add(pending)
            step.status, job.status, site.status = "waiting", "awaiting_approval", "awaiting_approval" if site.status != "live" else "live"
            db.commit()
            rec.emit("approval_required", step.key, a.description, "warning", {"approval_id": pending.id, "action": a.action, "details": a.details})
            notify(db, website=site, job_id=job.id, title=f"Approval needed: {site.name}", message=a.description, level="warning", link="/approvals")
            return "waiting"
        except JobCancelled:
            raise
        except Exception as exc:  # noqa: BLE001 — classified below
            err = classify(exc)
            tb = traceback.format_exc(limit=8)
            rec.emit("step_error", step.key, err.message, "error", {**err.to_dict(), "attempt": step.attempts, "traceback": tb})
            if err.retryable and attempt < settings.STEP_RETRIES:
                delay = min(60, 2 ** (attempt + 1)) + random.uniform(0, 1)
                step.status = "retrying"
                db.commit()
                rec.emit("step_retry", step.key, f"Transient error — retrying in {delay:.0f}s ({attempt + 1}/{settings.STEP_RETRIES})", "warning", {"delay": delay})
                await asyncio.sleep(delay)
                continue
            _persist_state(db, site, ctx)
            return _fail_step(db, rec, job, site, step, err, tb)

        _persist_state(db, site, ctx)
        step.status, step.progress, step.finished_at = "completed", 100.0, utcnow()
        step.output = output or {}
        rec._recalc_job_progress()
        db.commit()
        rec.emit("step_completed", step.key, (output or {}).get("summary", ""), "success", {"output": output or {}, "duration_s": _duration(step)})
        return "ok"
    return "failed"


def _persist_state(db: Session, site: Website, ctx: StepContext) -> None:
    site.config = ctx.state
    flag_modified(site, "config")
    for k, v in ctx.site_updates.items():
        setattr(site, k, v)
    db.commit()


def _fail_step(db, rec: Recorder, job: Job, site: Website, step: JobStep, err: PipelineError, tb: str | None) -> str:
    step.status, step.error, step.finished_at = "failed", err.message, utcnow()
    step.output = {**(step.output or {}), "error": err.to_dict()}
    rec.emit("step_failed", step.key, err.message, "error", err.to_dict())
    _finish(db, rec, job, site, "failed", err.message, level="error", hint=err.hint)
    return "failed"


def _finish(db, rec: Recorder, job: Job, site: Website, status: str, message: str, level: str, hint: str | None = None) -> None:
    job.status, job.error, job.finished_at = status, (message if status == "failed" else None), utcnow()
    # A failed job never takes down a site that is already live, nor discards a working preview.
    if site.status != "live" or not site.current_deployment_id:
        if (site.config or {}).get("preview"):
            site.status = "preview"
        else:
            site.status = "failed" if status == "failed" else ("draft" if status == "cancelled" else site.status)
    db.commit()
    rec.emit(f"job_{status}", job.current_step, message, level, {"hint": hint})
    notify(db, website=site, job_id=job.id, title=f"{'Job failed' if status == 'failed' else 'Job cancelled'}: {site.name}",
           message=message + (f" — {hint}" if hint else ""), level=level)


def _duration(step: JobStep) -> float | None:
    if step.started_at and step.finished_at:
        a, b = step.started_at, step.finished_at
        if a.tzinfo is None or b.tzinfo is None:
            a, b = a.replace(tzinfo=None), b.replace(tzinfo=None)
        return round((b - a).total_seconds(), 2)
    return None
