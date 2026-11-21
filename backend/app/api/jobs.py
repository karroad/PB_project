from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import SessionLocal, get_db
from ..deps import accessible_website_ids, audit, get_current_user, get_website_for_user, require_role
from ..events import bus
from ..models import Approval, Job, JobEvent, User, utcnow
from ..orchestrator.queue import queue
from .serializers import approval_out, job_out

router = APIRouter(prefix="/api", tags=["jobs"])


def _job_for(db: Session, user: User, job_id: str, write: bool = False) -> Job:
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    get_website_for_user(db, user, job.website_id, write=write)
    return job


@router.get("/jobs")
def list_jobs(status: str | None = None, limit: int = Query(100, le=500), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = select(Job).order_by(Job.created_at.desc()).limit(limit)
    ids = accessible_website_ids(db, user)
    if ids is not None:
        q = q.where(Job.website_id.in_(ids))
    if status:
        q = q.where(Job.status == status)
    return [job_out(j) for j in db.scalars(q)]


@router.get("/jobs/{job_id}")
def get_job(job_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    job = _job_for(db, user, job_id)
    approvals = db.scalars(select(Approval).where(Approval.job_id == job.id).order_by(Approval.requested_at)).all()
    last_event = db.scalar(select(JobEvent.id).where(JobEvent.job_id == job.id).order_by(JobEvent.id.desc()))
    return {**job_out(job, steps=True), "approvals": [approval_out(a) for a in approvals], "last_event_id": last_event or 0}


@router.get("/jobs/{job_id}/history")
def job_history(job_id: str, after: int = 0, limit: int = Query(1000, le=5000), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _job_for(db, user, job_id)
    rows = db.scalars(select(JobEvent).where(JobEvent.job_id == job_id, JobEvent.id > after).order_by(JobEvent.id).limit(limit))
    return [_event_dict(e) for e in rows]


def _event_dict(e: JobEvent) -> dict:
    return {"id": e.id, "type": e.type, "job_id": e.job_id, "website_id": e.website_id, "step": e.step_key, "level": e.level,
            "message": e.message, "data": e.data or {}, "ts": e.created_at.isoformat()}


def _sse(event: dict) -> str:
    return f"id: {event.get('id', '')}\nevent: message\ndata: {json.dumps(event, default=str)}\n\n"


@router.get("/jobs/{job_id}/events")
async def job_events(job_id: str, request: Request, after: int = 0, user: User = Depends(get_current_user)):
    """SSE stream: replays persisted events after `after`, then streams live ones."""
    db = SessionLocal()
    try:
        _job_for(db, user, job_id)
    finally:
        db.close()
    last_id = int(request.headers.get("last-event-id") or after or 0)
    q = bus.subscribe(f"job:{job_id}")

    async def gen():
        nonlocal last_id
        try:
            s = SessionLocal()
            try:
                for e in s.scalars(select(JobEvent).where(JobEvent.job_id == job_id, JobEvent.id > last_id).order_by(JobEvent.id)):
                    last_id = e.id
                    yield _sse(_event_dict(e))
            finally:
                s.close()
            yield ": connected\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if ev.get("job_id") != job_id or (ev.get("id") and ev["id"] <= last_id):
                    continue
                if ev.get("id"):
                    last_id = ev["id"]
                yield _sse(ev)
        finally:
            bus.unsubscribe(f"job:{job_id}", q)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/events")
async def global_events(request: Request, user: User = Depends(get_current_user)):
    """Portfolio-wide live stream (status changes, health, notifications) filtered by access rights."""
    db = SessionLocal()
    try:
        allowed = accessible_website_ids(db, user)
    finally:
        db.close()
    allowed_set = None if allowed is None else set(allowed)
    q = bus.subscribe("*")

    async def gen():
        try:
            yield ": connected\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if ev.get("type") == "notification":
                    if ev.get("user_id") != user.id:
                        continue
                elif ev.get("type") == "log":
                    continue  # keep the global stream light; per-job streams carry logs
                elif allowed_set is not None and ev.get("website_id") not in allowed_set:
                    continue
                yield _sse({k: v for k, v in ev.items() if k != "id"})
        finally:
            bus.unsubscribe("*", q)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/jobs/{job_id}/retry")
async def retry_job(job_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(require_role("operator"))):
    job = _job_for(db, user, job_id, write=True)
    if job.status not in ("failed", "cancelled"):
        raise HTTPException(409, f"Only failed or cancelled jobs can be retried (status: {job.status})")
    for s in job.steps:
        if s.status in ("failed", "running", "retrying", "waiting"):
            s.status, s.error = "pending", None
    # earlier rejections no longer apply: the retried step will ask for a fresh decision
    for a in db.scalars(select(Approval).where(Approval.job_id == job.id, Approval.status == "rejected")):
        a.status = "superseded"
    job.status, job.cancel_requested, job.error, job.finished_at = "queued", False, None, None
    db.commit()
    await queue.enqueue(job.id)
    audit(db, user, "job.retry", "job", job.id, request=request)
    return job_out(job, steps=True)


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(require_role("operator"))):
    job = _job_for(db, user, job_id, write=True)
    if job.status in ("completed", "failed", "cancelled"):
        raise HTTPException(409, "Job already finished")
    if job.status in ("queued", "awaiting_approval"):
        job.status, job.finished_at = "cancelled", utcnow()
        for a in db.scalars(select(Approval).where(Approval.job_id == job.id, Approval.status == "pending")):
            a.status = "rejected"
        site = job.website
        if site.status in ("generating", "awaiting_approval"):
            site.status = "live" if site.current_deployment_id else "draft"
    else:
        job.cancel_requested = True  # running: stops before the next step
    db.commit()
    bus.publish(f"job:{job.id}", {"type": "job_cancel_requested", "job_id": job.id, "website_id": job.website_id, "message": "Cancellation requested"})
    audit(db, user, "job.cancel", "job", job.id, request=request)
    return job_out(job, steps=True)
