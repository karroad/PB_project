"""User notifications: persisted in-app notifications + live push + optional webhook."""
from __future__ import annotations

import asyncio
import logging

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .events import bus
from .models import Notification, User, Website

log = logging.getLogger("siteforge.notify")
ICON = {"info": "ℹ️", "success": "✅", "warning": "⚠️", "error": "❌"}


async def _webhook(text: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.post(settings.NOTIFY_WEBHOOK_URL, json={"text": text, "content": text})
    except httpx.HTTPError as e:
        log.warning("Notification webhook failed: %s", e)


def notify(db: Session, *, website: Website | None, title: str, message: str = "", level: str = "info",
           job_id: str | None = None, link: str | None = None) -> None:
    recipients = {u.id for u in db.scalars(select(User).where(User.role == "admin", User.is_active.is_(True)))}
    if website and website.owner_id:
        recipients.add(website.owner_id)
    rows = []
    for uid in recipients:
        n = Notification(user_id=uid, website_id=website.id if website else None, job_id=job_id, level=level, title=title, message=message,
                         link=link or (f"/sites/{website.id}" if website else None))
        db.add(n)
        rows.append(n)
    db.commit()
    for n in rows:
        bus.publish("*", {"type": "notification", "user_id": n.user_id, "website_id": n.website_id, "notification": {
            "id": n.id, "title": n.title, "message": n.message, "level": n.level, "link": n.link, "created_at": n.created_at.isoformat(), "read": False}})
    if settings.NOTIFY_WEBHOOK_URL:
        try:
            asyncio.get_running_loop().create_task(_webhook(f"{ICON.get(level, '')} {title}\n{message}"))
        except RuntimeError:
            pass
