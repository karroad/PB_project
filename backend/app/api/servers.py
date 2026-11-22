"""SSH keys and user-managed servers."""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import audit, require_role
from ..errors import PipelineError
from ..models import Server, SSHKey, User, Website
from ..security import encrypt_secret
from ..servers import ops
from ..servers.connection import generate_keypair, inspect_private_key

router = APIRouter(prefix="/api", tags=["servers"])
HOST_RE = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$|^[0-9a-fA-F:]+$")
USER_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
PATH_RE = re.compile(r"^/[A-Za-z0-9._/-]{1,200}$")


class KeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    generate: bool = False
    private_key: str | None = Field(default=None, max_length=20000)
    passphrase: str | None = Field(default=None, max_length=200)


class ServerIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    provider: str = Field(default="other", pattern="^(hetzner|ovh|hostinger|other)$")
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(default=22, ge=1, le=65535)
    username: str = "root"
    ssh_key_id: str | None = None
    base_dir: str = "/srv/siteforge"
    max_sites: int | None = Field(default=None, ge=1, le=1000)
    simulated: bool = False

    @field_validator("host")
    @classmethod
    def _host(cls, v):
        v = v.strip()
        if not HOST_RE.match(v):
            raise ValueError("Enter a hostname or IP address")
        return v

    @field_validator("username")
    @classmethod
    def _user(cls, v):
        if not USER_RE.match(v):
            raise ValueError("Invalid Linux user name")
        return v

    @field_validator("base_dir")
    @classmethod
    def _base(cls, v):
        if not PATH_RE.match(v) or ".." in v or v.rstrip("/") in ("", "/etc", "/usr", "/bin", "/root", "/var"):
            raise ValueError("Use a dedicated absolute folder such as /srv/siteforge")
        return v.rstrip("/")


def key_out(k: SSHKey, used_by: int = 0) -> dict:
    return {"id": k.id, "name": k.name, "public_key": k.public_key, "fingerprint": k.fingerprint, "key_type": k.key_type,
            "used_by": used_by, "created_at": k.created_at.isoformat()}


def server_out(db: Session, s: Server) -> dict:
    sites = db.execute(select(Website.id, Website.name, Website.status, Website.domain, Website.live_url)
                       .where(Website.server_id == s.id, Website.status != "archived")).all()
    key = db.get(SSHKey, s.ssh_key_id) if s.ssh_key_id else None
    return {"id": s.id, "name": s.name, "provider": s.provider, "host": s.host, "port": s.port, "username": s.username,
            "ssh_key_id": s.ssh_key_id, "ssh_key_name": key.name if key else None, "base_dir": s.base_dir, "simulated": s.simulated,
            "status": s.status, "os_info": s.os_info, "web_server": s.web_server, "metrics": s.metrics or {}, "max_sites": s.max_sites,
            "web_config": ops.web_config(s) if s.web_server == "traefik" else None,
            "web_overrides": (s.web_config or {}).get("overrides") or {}, "web_conflict": bool((s.web_config or {}).get("conflict")),
            "error": s.error, "host_key_pinned": bool(s.host_key), "last_checked_at": s.last_checked_at.isoformat() if s.last_checked_at else None,
            "sites": [{"id": i, "name": n, "status": st, "domain": d, "url": u} for i, n, st, d, u in sites], "created_at": s.created_at.isoformat()}


# ---------------------------------------------------------------- SSH keys
@router.get("/ssh-keys")
def list_keys(db: Session = Depends(get_db), _: User = Depends(require_role("operator"))):
    usage = dict(db.execute(select(Server.ssh_key_id, func.count()).group_by(Server.ssh_key_id)).all())
    return [key_out(k, usage.get(k.id, 0)) for k in db.scalars(select(SSHKey).order_by(SSHKey.created_at))]


@router.post("/ssh-keys", status_code=201)
def create_key(body: KeyCreate, request: Request, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    if body.generate:
        private, public, fp = generate_keypair(comment=f"siteforge-{re.sub(r'[^a-z0-9-]', '-', body.name.lower())[:30]}")
        algo, passphrase = "ssh-ed25519", None
    else:
        if not body.private_key:
            raise HTTPException(422, "Paste a private key or choose Generate")
        try:
            public, fp, algo = inspect_private_key(body.private_key, body.passphrase)
        except PipelineError as e:
            raise HTTPException(422, e.message)
        private, passphrase = body.private_key.strip() + "\n", body.passphrase
    if db.scalar(select(SSHKey.id).where(SSHKey.fingerprint == fp)):
        raise HTTPException(409, "This key is already stored")
    k = SSHKey(name=body.name, public_key=public, fingerprint=fp, key_type=algo, created_by=user.id,
               private_key_encrypted=encrypt_secret({"private_key": private, "passphrase": passphrase}))
    db.add(k)
    db.commit()
    audit(db, user, "ssh_key.create", "ssh_key", k.id, {"name": k.name, "fingerprint": fp, "generated": body.generate}, request)
    return key_out(k)


@router.delete("/ssh-keys/{key_id}")
def delete_key(key_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    k = db.get(SSHKey, key_id)
    if not k:
        raise HTTPException(404, "Key not found")
    if db.scalar(select(Server.id).where(Server.ssh_key_id == key_id)):
        raise HTTPException(409, "Key is used by a server — attach another key to it first")
    db.delete(k)
    db.commit()
    audit(db, user, "ssh_key.delete", "ssh_key", key_id, {"name": k.name}, request)
    return {"deleted": True}


# ---------------------------------------------------------------- servers
@router.get("/servers")
def list_servers(db: Session = Depends(get_db), _: User = Depends(require_role("operator"))):
    return [server_out(db, s) for s in db.scalars(select(Server).order_by(Server.created_at))]


@router.get("/servers/{server_id}")
def get_server(server_id: str, db: Session = Depends(get_db), _: User = Depends(require_role("operator"))):
    s = db.get(Server, server_id)
    if not s:
        raise HTTPException(404, "Server not found")
    return server_out(db, s)


@router.post("/servers", status_code=201)
async def create_server(body: ServerIn, request: Request, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    if body.simulated and not settings.SANDBOX_PROVIDERS:
        raise HTTPException(422, "Simulated servers are only available in sandbox mode")
    if not body.simulated and not (body.ssh_key_id and db.get(SSHKey, body.ssh_key_id)):
        raise HTTPException(422, "Choose an SSH key for this server")
    s = Server(**body.model_dump(), created_by=user.id)
    if s.simulated:
        s.host = "127.0.0.1"
    db.add(s)
    db.commit()
    audit(db, user, "server.create", "server", s.id, {"name": s.name, "host": s.host, "provider": s.provider}, request)
    await ops.test_connection(s.id)  # check immediately so the user sees problems right away
    db.refresh(s)
    return server_out(db, s)


@router.patch("/servers/{server_id}")
def update_server(server_id: str, body: dict, request: Request, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    s = db.get(Server, server_id)
    if not s:
        raise HTTPException(404, "Server not found")
    if "web_overrides" in body:  # admin corrections for an auto-detected Traefik (network, entrypoint, resolver)
        ov = body.pop("web_overrides") or {}
        if not isinstance(ov, dict) or set(ov) - set(ops.WEB_CONFIG_KEYS):
            raise HTTPException(422, f"Traefik settings can only include {', '.join(ops.WEB_CONFIG_KEYS)}")
        for k, v in ov.items():
            if v and not (isinstance(v, str) and ops.NAME_RE.match(v)):
                raise HTTPException(422, f"Invalid {k}: use letters, digits, dot, dash or underscore")
        s.web_config = {**(s.web_config or {}), "overrides": {k: v for k, v in ov.items() if v}}
        if s.status == "ready" and s.web_server == "traefik":
            s.status = "ok"  # run Prepare again so the new settings are checked
    allowed = {k: v for k, v in body.items() if k in ("name", "provider", "ssh_key_id", "max_sites", "username", "port")}
    merged = ServerIn(**{**{f: getattr(s, f) for f in ServerIn.model_fields}, **allowed})  # validates the result
    if allowed.get("ssh_key_id") and not db.get(SSHKey, allowed["ssh_key_id"]):
        raise HTTPException(422, "Unknown SSH key")
    for k in allowed:
        setattr(s, k, getattr(merged, k))
    s.status = "new" if {"ssh_key_id", "username", "port"} & set(allowed) else s.status
    db.commit()
    audit(db, user, "server.update", "server", s.id, {**allowed, **({"web_overrides": s.web_config.get("overrides")} if s.web_config else {})}, request)
    return server_out(db, s)


@router.post("/servers/{server_id}/test")
async def test_server(server_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(require_role("operator"))):
    if not db.get(Server, server_id):
        raise HTTPException(404, "Server not found")
    result = await ops.test_connection(server_id)
    audit(db, user, "server.test", "server", server_id, {"ok": result.get("ok")}, request)
    return result


@router.post("/servers/{server_id}/provision")
async def provision_server(server_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    if not db.get(Server, server_id):
        raise HTTPException(404, "Server not found")
    lines: list[str] = []

    async def log(m: str):
        lines.append(m)

    try:
        await ops.provision(server_id, log)
    except PipelineError as e:
        audit(db, user, "server.provision_failed", "server", server_id, {"error": e.message}, request)
        raise HTTPException(502, e.message + (f" — {e.hint}" if e.hint else ""))
    audit(db, user, "server.provision", "server", server_id, {}, request)
    db.expire_all()
    return {**server_out(db, db.get(Server, server_id)), "log": lines}


@router.post("/servers/{server_id}/refresh")
async def refresh_server(server_id: str, db: Session = Depends(get_db), _: User = Depends(require_role("operator"))):
    if not db.get(Server, server_id):
        raise HTTPException(404, "Server not found")
    try:
        await ops.refresh_metrics(server_id)
    except PipelineError as e:
        raise HTTPException(502, e.message)
    db.expire_all()
    return server_out(db, db.get(Server, server_id))


@router.post("/servers/{server_id}/reset-host-key")
def reset_host_key(server_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    s = db.get(Server, server_id)
    if not s:
        raise HTTPException(404, "Server not found")
    s.host_key, s.status = None, "new"
    db.commit()
    audit(db, user, "server.reset_host_key", "server", s.id, {}, request)
    return server_out(db, s)


@router.delete("/servers/{server_id}")
def delete_server(server_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    s = db.get(Server, server_id)
    if not s:
        raise HTTPException(404, "Server not found")
    if db.scalar(select(Website.id).where(Website.server_id == server_id, Website.status != "archived")):
        raise HTTPException(409, "Websites are still hosted on this server — move or delete them first")
    db.delete(s)
    db.commit()
    audit(db, user, "server.delete", "server", server_id, {"name": s.name, "host": s.host}, request)
    return {"deleted": True}
