"""Hosting adapters: where a built website runs.

Every adapter implements the same lifecycle so the orchestrator never needs to know
provider details: public_url → plan → provision → deploy → (restart | rollback).
"""
from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Awaitable, Callable

import httpx

from ...config import settings
from ...errors import ConfigurationError, PipelineError, RetryableError

LogFn = Callable[[str], Awaitable[None]]

STATIC_DOCKERFILE = """FROM nginx:1.27-alpine
COPY build/ /usr/share/nginx/html/
COPY nginx.conf /etc/nginx/conf.d/default.conf
HEALTHCHECK --interval=30s --timeout=3s CMD wget -qO- http://localhost/ >/dev/null || exit 1
"""

NGINX_CONF = """server {
  listen 80;
  root /usr/share/nginx/html;
  add_header X-Content-Type-Options nosniff always;
  add_header X-Frame-Options SAMEORIGIN always;
  add_header Referrer-Policy strict-origin-when-cross-origin always;
  add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;
  location / { try_files $uri $uri/ /404.html; }
}
"""


class HostingAdapter:
    key = "base"
    name = "Base"
    description = ""
    requires_approval = False
    credential_fields: list[str] = []
    external = False

    def enabled(self) -> tuple[bool, str]:
        return True, ""

    def public_url(self, site) -> str:
        raise NotImplementedError

    def plan(self, site, spec: dict) -> dict:
        return {"provider": self.key, "resources": "shared", "isolation": "per-site directory"}

    async def provision(self, site, creds: dict, log: LogFn) -> dict:
        return {}

    async def deploy(self, site, build_dir: Path, source_dir: Path, version: int, creds: dict, infra: dict, log: LogFn) -> dict:
        raise NotImplementedError

    async def restart(self, site, deployment) -> str:
        return "Nothing to restart for this provider"

    async def activate(self, site, deployment, log: LogFn | None = None) -> None:
        """Make an existing deployment the live one (used for rollback)."""

    async def test_credentials(self, creds: dict) -> tuple[bool, str]:
        return True, "No credentials required"

    def catalog(self) -> dict:
        ok, reason = self.enabled()
        return {"key": self.key, "name": self.name, "description": self.description, "requires_approval": self.requires_approval,
                "credential_fields": self.credential_fields, "enabled": ok, "disabled_reason": reason, "external": self.external}


def _deploy_dir(slug: str, version: int) -> Path:
    return settings.deployments_dir / slug / f"v{version}"


class LocalHosting(HostingAdapter):
    key = "local"
    name = "Local static hosting"
    description = "Served by the platform itself with security headers — at /sites/<slug>/, or on the site's own domain when the server is public."

    def public_url(self, site) -> str:
        # With a public server, the platform routes requests by Host header to the right site.
        if site.domain and settings.SERVER_PUBLIC_IP:
            return f"http://{site.domain}/"
        return f"{settings.PUBLIC_BASE_URL.rstrip('/')}/sites/{site.slug}/"

    async def deploy(self, site, build_dir, source_dir, version, creds, infra, log):
        dest = _deploy_dir(site.slug, version)
        if dest.exists():
            shutil.rmtree(dest)
        await log(f"Publishing immutable artefact v{version}")
        shutil.copytree(build_dir, dest / "build")
        return {"url": self.public_url(site), "artifact_path": str(dest / "build"), "details": {"mode": "static"}}


class DockerHosting(HostingAdapter):
    key = "docker"
    name = "Docker (local engine + Traefik)"
    description = "Each site runs in its own nginx container behind Traefik, isolated with its own restart policy and health check."

    def enabled(self):
        if not settings.DOCKER_ENABLED:
            return False, "Set DOCKER_ENABLED=true on the backend"
        if not shutil.which("docker"):
            return False, "Docker CLI not found on the server"
        return True, ""

    def public_url(self, site) -> str:
        return f"http://{site.domain or site.slug + '.localhost'}/"

    def plan(self, site, spec):
        return {"provider": self.key, "resources": {"cpu": "0.25", "memory": "128m"}, "isolation": "container per site", "proxy": "traefik"}

    async def _run(self, *cmd: str, cwd: Path) -> str:
        proc = await asyncio.create_subprocess_exec(*cmd, cwd=cwd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        out, _ = await proc.communicate()
        text = out.decode(errors="ignore")
        if proc.returncode != 0:
            raise PipelineError(f"`{' '.join(cmd[:3])}` failed", code="docker_error", details={"output": text[-1500:]},
                                hint="Is the Docker daemon running and the `siteforge` network created? See infra/traefik.")
        return text

    async def deploy(self, site, build_dir, source_dir, version, creds, infra, log):
        ok, reason = self.enabled()
        if not ok:
            raise ConfigurationError(f"Docker hosting unavailable: {reason}")
        dest = _deploy_dir(site.slug, version)
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(build_dir, dest / "build")
        (dest / "Dockerfile").write_text(STATIC_DOCKERFILE)
        (dest / "nginx.conf").write_text(NGINX_CONF)
        host = site.domain or f"{site.slug}.localhost"
        compose = f"""services:
  web:
    build: .
    image: siteforge/{site.slug}:v{version}
    restart: unless-stopped
    mem_limit: 128m
    cpus: 0.25
    networks: [siteforge]
    labels:
      - traefik.enable=true
      - traefik.http.routers.sf-{site.slug}.rule=Host(`{host}`)
      - traefik.http.services.sf-{site.slug}.loadbalancer.server.port=80
networks:
  siteforge:
    external: true
"""
        (dest / "docker-compose.yml").write_text(compose)
        await log(f"docker compose up (image siteforge/{site.slug}:v{version})")
        await self._run("docker", "compose", "-p", f"sf-{site.slug}", "up", "-d", "--build", cwd=dest)
        return {"url": self.public_url(site), "artifact_path": str(dest / "build"), "details": {"mode": "docker", "compose": str(dest)}}

    async def activate(self, site, deployment, log=None):
        compose_dir = Path(deployment.details.get("compose", ""))
        if compose_dir.exists():
            await self._run("docker", "compose", "-p", f"sf-{site.slug}", "up", "-d", cwd=compose_dir)

    async def restart(self, site, deployment):
        compose_dir = Path(deployment.details.get("compose", ""))
        await self._run("docker", "compose", "-p", f"sf-{site.slug}", "restart", cwd=compose_dir)
        return "Container restarted"


class HetznerHosting(HostingAdapter):
    key = "hetzner"
    name = "Hetzner Cloud"
    description = "Provisions a dedicated cloud server via the Hetzner API (cloud-init installs Docker + Caddy with automatic HTTPS) and uploads the artefact over SSH."
    requires_approval = True
    external = True
    credential_fields = ["api_token", "ssh_key_name", "ssh_private_key_path", "server_type", "location"]
    API = "https://api.hetzner.cloud/v1"

    def public_url(self, site) -> str:
        return f"https://{site.domain}/" if site.domain else "pending://server-ip"

    def plan(self, site, spec):
        return {"provider": self.key, "resources": {"server_type": "cx22", "location": "fsn1"}, "isolation": "dedicated VM", "tls": "Caddy automatic HTTPS"}

    def _headers(self, creds):
        if not creds.get("api_token"):
            raise ConfigurationError("Hetzner account has no api_token", hint="Add a Hetzner provider account under Providers.")
        return {"Authorization": f"Bearer {creds['api_token']}"}

    async def test_credentials(self, creds):
        try:
            async with httpx.AsyncClient(timeout=20) as c:
                r = await c.get(f"{self.API}/servers?per_page=1", headers=self._headers(creds))
            return r.status_code == 200, f"HTTP {r.status_code}"
        except (httpx.HTTPError, ConfigurationError) as e:
            return False, str(e)

    async def provision(self, site, creds, log):
        domain = site.domain or ""
        cloud_init = f"""#cloud-config
packages: [caddy, rsync]
write_files:
  - path: /etc/caddy/Caddyfile
    content: |
      {domain or ':80'} {{
        root * /srv/site
        file_server
        header X-Content-Type-Options nosniff
        header X-Frame-Options SAMEORIGIN
      }}
runcmd: [mkdir -p /srv/site, systemctl restart caddy]
"""
        body = {"name": f"sf-{site.slug}", "server_type": creds.get("server_type", "cx22"), "location": creds.get("location", "fsn1"),
                "image": "ubuntu-24.04", "user_data": cloud_init, "labels": {"siteforge": "true", "site": site.slug}}
        if creds.get("ssh_key_name"):
            body["ssh_keys"] = [creds["ssh_key_name"]]
        async with httpx.AsyncClient(timeout=60) as c:
            existing = await c.get(f"{self.API}/servers", params={"label_selector": f"site={site.slug}"}, headers=self._headers(creds))
            existing.raise_for_status()
            servers = existing.json().get("servers", [])
            if servers:
                server = servers[0]
                await log(f"Reusing existing server {server['name']}")
            else:
                await log("Creating Hetzner server")
                r = await c.post(f"{self.API}/servers", json=body, headers=self._headers(creds))
                r.raise_for_status()
                server = r.json()["server"]
            for _ in range(60):
                s = await c.get(f"{self.API}/servers/{server['id']}", headers=self._headers(creds))
                s.raise_for_status()
                server = s.json()["server"]
                if server["status"] == "running":
                    break
                await asyncio.sleep(5)
            else:
                raise RetryableError("Server did not reach 'running' state in time", code="provision_timeout")
        ip = server["public_net"]["ipv4"]["ip"]
        await log(f"Server running at {ip}")
        return {"server_id": server["id"], "ipv4": ip}

    async def deploy(self, site, build_dir, source_dir, version, creds, infra, log):
        ip = infra.get("ipv4")
        key = creds.get("ssh_private_key_path")
        if not ip or not key:
            raise ConfigurationError("Hetzner deploy needs a provisioned server and ssh_private_key_path")
        if not shutil.which("scp"):
            raise ConfigurationError("scp is not installed on the platform server")
        await log(f"Uploading artefact to {ip}")
        proc = await asyncio.create_subprocess_exec(
            "scp", "-i", key, "-o", "StrictHostKeyChecking=accept-new", "-r", f"{build_dir}/.", f"root@{ip}:/srv/site/",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        out, _ = await proc.communicate()
        if proc.returncode != 0:
            raise RetryableError("Upload over SSH failed", code="ssh_error", details={"output": out.decode(errors="ignore")[-800:]})
        url = f"https://{site.domain}/" if site.domain else f"http://{ip}/"
        return {"url": url, "artifact_path": str(build_dir), "details": {"mode": "hetzner", "ip": ip}}


class ServerHosting(HostingAdapter):
    """Deploys to one of the user's own servers over SSH (Caddy + automatic HTTPS, atomic releases)."""

    key = "server"
    name = "Your servers (SSH)"
    description = "Deploy to a server you manage (Hetzner, OVH, Hostinger VPS…) using your SSH key. Automatic HTTPS, instant rollback."
    always_provision = True  # make sure the server is prepared before the first deploy

    def _server(self, site):
        from ...database import SessionLocal
        from ...models import Server

        if not getattr(site, "server_id", None):
            raise ConfigurationError("No server selected for this website", hint="Choose one of your servers in the Publish dialog.")
        db = SessionLocal()
        try:
            s = db.get(Server, site.server_id)
            if s:
                db.expunge(s)
            return s
        finally:
            db.close()

    def public_url(self, site) -> str:
        from ...servers.ops import site_host

        server = self._server(site)
        if not server:
            return "pending://server"
        if server.simulated:  # sandbox: browse it through the platform
            return f"{settings.PUBLIC_BASE_URL.rstrip('/')}/simhost/{server.id}/{site.slug}/"
        host = site_host(server, site.slug, site.domain)
        return f"https://{host}/" if site.domain else f"http://{host}/"

    def plan(self, site, spec):
        server = self._server(site)
        traefik = bool(server and server.web_server == "traefik")
        return {"provider": "server", "server": server.name if server else None, "host": server.host if server else None,
                "isolation": "own read-only container behind the existing Traefik" if traefik else "own release folder + web-server site block",
                "tls": ("Traefik certificate resolver" if traefik else "Caddy automatic HTTPS") if site.domain else "HTTP (no domain yet)"}

    async def provision(self, site, creds, log):
        from ...servers import ops

        server = self._server(site)
        if not server:
            raise ConfigurationError("The selected server no longer exists", hint="Choose another server in the Publish dialog.")
        if server.status != "ready":
            await log(f"Preparing {server.name} (first deploy)")
            return await ops.provision(server.id, log)
        await log(f"Server {server.name} is ready")
        return {"ipv4": "127.0.0.1" if server.simulated else ops.server_ip(server)}

    async def deploy(self, site, build_dir, source_dir, version, creds, infra, log):
        from ...servers import ops

        server = self._server(site)
        result = await ops.deploy_site(server.id, site.slug, site.domain, build_dir, version, log)
        return {"url": self.public_url(site), "artifact_path": result["release"], "details": {"mode": "server", **result}}

    async def activate(self, site, deployment, log=None):
        from ...servers import ops

        await ops.activate_release(deployment.details["server_id"], site.slug, deployment.details["release"])

    async def restart(self, site, deployment):
        from ...servers import ops

        return await ops.restart_site(self._server(site).id, site.slug)

    async def verify(self, site, url: str) -> dict:
        from ...servers import ops

        server = self._server(site)
        code = await ops.verify_on_server(server.id, ops.site_host(server, site.slug, site.domain))
        return {"checked": True, "status": 200 if code in (200, 301, 302, 308) else code, "raw_status": code, "via": f"server {server.name}",
                "https": bool(site.domain)}


HOSTING: dict[str, HostingAdapter] = {a.key: a for a in (LocalHosting(), ServerHosting(), DockerHosting(), HetznerHosting())}
PLANNED_HOSTING = [
    {"key": "ovh", "name": "OVHcloud", "description": "Planned: Public Cloud instances via OVH API", "enabled": False, "disabled_reason": "Planned adapter"},
    {"key": "hostinger", "name": "Hostinger", "description": "Planned: VPS API integration", "enabled": False, "disabled_reason": "Planned adapter"},
]


def get_hosting(key: str) -> HostingAdapter:
    if key not in HOSTING:
        raise ConfigurationError(f"Unknown hosting provider '{key}'")
    return HOSTING[key]
