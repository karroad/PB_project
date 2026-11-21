from fastapi import Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .models import AuditLog, User, Website, WebsiteMember
from .security import ROLE_RANK, decode_access_token


def _token_from_request(request: Request, token_q: str | None) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:]
    return token_q  # EventSource cannot set headers, so SSE passes ?token=


def get_current_user(
    request: Request, token: str | None = Query(default=None), db: Session = Depends(get_db)
) -> User:
    raw = _token_from_request(request, token)
    payload = decode_access_token(raw) if raw else None
    if not payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    user = db.get(User, payload["sub"])
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User inactive or missing")
    return user


def require_role(min_role: str):
    def checker(user: User = Depends(get_current_user)) -> User:
        if ROLE_RANK.get(user.role, -1) < ROLE_RANK[min_role]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires role '{min_role}'")
        return user

    return checker


def accessible_website_ids(db: Session, user: User) -> list[str] | None:
    """None means unrestricted (admin)."""
    if user.role == "admin":
        return None
    owned = db.scalars(select(Website.id).where(Website.owner_id == user.id)).all()
    shared = db.scalars(select(WebsiteMember.website_id).where(WebsiteMember.user_id == user.id)).all()
    return list(set(owned) | set(shared))


def get_website_for_user(db: Session, user: User, website_id: str, write: bool = False) -> Website:
    site = db.get(Website, website_id)
    if not site:
        raise HTTPException(404, "Website not found")
    if user.role == "admin":
        return site
    if site.owner_id == user.id:
        if write and user.role == "viewer":
            raise HTTPException(403, "Viewers cannot modify websites")
        return site
    member = db.scalar(
        select(WebsiteMember).where(WebsiteMember.website_id == website_id, WebsiteMember.user_id == user.id)
    )
    if not member:
        raise HTTPException(404, "Website not found")
    if write and (member.role != "editor" or user.role == "viewer"):
        raise HTTPException(403, "You have read-only access to this website")
    return site


def audit(
    db: Session,
    user: User | None,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    details: dict | None = None,
    request: Request | None = None,
) -> None:
    db.add(
        AuditLog(
            user_id=user.id if user else None,
            user_email=user.email if user else "system",
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=details or {},
            ip=request.client.host if request and request.client else None,
        )
    )
    db.commit()
