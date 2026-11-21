from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import audit, get_current_user, require_role
from ..models import User
from ..schemas import LoginIn, UserCreate, UserOut, UserUpdate
from ..security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/api", tags=["auth"])
_failed: dict[str, int] = {}


@router.post("/auth/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    key = f"{request.client.host if request.client else ''}:{body.email.lower()}"
    if _failed.get(key, 0) >= 10:
        raise HTTPException(429, "Too many failed attempts — try again later")
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if not user or not user.is_active or not verify_password(body.password, user.password_hash):
        _failed[key] = _failed.get(key, 0) + 1
        audit(db, None, "auth.login_failed", details={"email": body.email}, request=request)
        raise HTTPException(401, "Invalid email or password")
    _failed.pop(key, None)
    audit(db, user, "auth.login", request=request)
    return {"access_token": create_access_token(user.id, user.role), "token_type": "bearer", "user": UserOut.model_validate(user).model_dump(mode="json")}


@router.get("/auth/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(require_role("admin"))):
    return db.scalars(select(User).order_by(User.created_at)).all()


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, request: Request, db: Session = Depends(get_db), admin: User = Depends(require_role("admin"))):
    if db.scalar(select(User).where(User.email == body.email.lower())):
        raise HTTPException(409, "A user with this email already exists")
    u = User(email=body.email.lower(), name=body.name, role=body.role, password_hash=hash_password(body.password))
    db.add(u)
    db.commit()
    audit(db, admin, "user.create", "user", u.id, {"email": u.email, "role": u.role}, request)
    return u


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: str, body: UserUpdate, request: Request, db: Session = Depends(get_db), admin: User = Depends(require_role("admin"))):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    if u.id == admin.id and (body.role not in (None, "admin") or body.is_active is False):
        raise HTTPException(400, "You cannot demote or deactivate yourself")
    changes = body.model_dump(exclude_none=True)
    if "password" in changes:
        u.password_hash = hash_password(changes.pop("password"))
    for k, v in changes.items():
        setattr(u, k, v)
    db.commit()
    audit(db, admin, "user.update", "user", u.id, {k: v for k, v in changes.items()}, request)
    return u
