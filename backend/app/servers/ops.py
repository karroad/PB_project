"""High-level operations on user-managed servers.

Layout on every server (base_dir defaults to /srv/siteforge):
    <base>/sites/<slug>/releases/v<N>/   immutable uploaded builds (last 5 kept)
    <base>/sites/<slug>/current          symlink to the live release (switched atomically)

Two web-server modes, chosen by looking at who owns ports 80/443 (never installs over another web server):
  caddy    nothing listens yet (or Caddy does): Caddy is installed on the host, one site block per website in
           /etc/caddy/siteforge/<slug>.caddy, automatic HTTPS.
  traefik  an existing Traefik (in Docker) owns 80/443: each website runs as a tiny read-only container
           "siteforge-<slug>" on Traefik's network, routed by Docker labels and using Traefik's own
           entrypoint + certificate resolver. The server's other sites are never touched.

Every command is a fixed template with shell-quoted arguments — users can't inject commands.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import re
from collections import Counter
import shlex
import socket
from pathlib import Path
from typing import Awaitable, Callable

from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..errors import ConfigurationError, PipelineError
from ..models import Server, SSHKey, utcnow
from ..security import decrypt_secret
from .connection import Connection, connect

LogFn = Callable[[str], Awaitable[None]]
CADDY_DIR = "/etc/caddy/siteforge"
CADDY_MAIN = "/etc/caddy/Caddyfile"
IMPORT_LINE = f"import {CADDY_DIR}/*.caddy"
KEEP_RELEASES = 5
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")  # docker network / traefik entrypoint / resolver names
SITE_IMAGE = "caddy:2.8-alpine"  # static file server inside each website container (traefik mode)
WEB_CONFIG_KEYS = ("network", "entrypoint", "http_entrypoint", "certresolver")


async def _nolog(_: str) -> None:
    pass


def q(s: str) -> str:
    return shlex.quote(s)


def sudo(server: Server, cmd: str) -> str:
    return cmd if server.username == "root" or server.simulated else f"sudo -n {cmd}"


def site_dir(server: Server, slug: str) -> str:
    if not SLUG_RE.match(slug):
        raise ConfigurationError(f"Invalid site slug {slug!r}")
    return f"{server.base_dir.rstrip('/')}/sites/{slug}"


def server_ip(server: Server) -> str | None:
    try:
        ipaddress.ip_address(server.host)
        return server.host
    except ValueError:
        try:
            return socket.gethostbyname(server.host)
        except OSError:
            return None


def site_host(server: Server, slug: str, domain: str | None) -> str:
    """Domain if set, otherwise a free wildcard-DNS name that points at the server (e.g. slug.1-2-3-4.sslip.io)."""
    if domain:
        return domain
    ip = server_ip(server) or "127.0.0.1"
    return f"{slug}.{ip.replace('.', '-').replace(':', '-')}.sslip.io"


def caddy_block(server: Server, slug: str, host: str, https: bool, address: str | None = None) -> str:
    address = address or (host if https else f"http://{host}")
    return f"""{address} {{
	root * {site_dir(server, slug)}/current
	encode zstd gzip
	file_server
	header {{
		X-Content-Type-Options nosniff
		X-Frame-Options SAMEORIGIN
		Referrer-Policy strict-origin-when-cross-origin
		-Server
	}}
	handle_errors {{
		rewrite * /404.html
		file_server
	}}
}}
"""


def load_key(db: Session, server: Server) -> tuple[str | None, str | None]:
    if server.simulated or not server.ssh_key_id:
        return None, None
    key = db.get(SSHKey, server.ssh_key_id)
    if not key:
        raise ConfigurationError("The server's SSH key was deleted", hint="Attach another SSH key to the server.")
    secret = decrypt_secret(key.private_key_encrypted)
    return secret.get("private_key"), secret.get("passphrase")


async def open_server(server_id: str) -> tuple[Server, Connection]:
    """Loads the server + key in a short DB session, connects, and pins the host key on first use."""
    db = SessionLocal()
    try:
        server = db.get(Server, server_id)
        if not server:
            raise ConfigurationError("Server not found", hint="It may have been deleted. Choose another server.")
        private_key, passphrase = load_key(db, server)
        conn = await connect(server, private_key, passphrase)
        if not server.host_key and conn.host_key:
            server.host_key = conn.host_key
            db.commit()
        db.expunge(server)
        return server, conn
    finally:
        db.close()


def _update(server_id: str, **fields) -> None:
    db = SessionLocal()
    try:
        s = db.get(Server, server_id)
        if s:
            for k, v in fields.items():
                setattr(s, k, v)
            db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------- web-server detection
def web_config(server: Server) -> dict:
    """Effective Traefik settings: what was detected, with the admin's overrides on top."""
    wc = server.web_config or {}
    return {**(wc.get("detected") or {}), **{k: v for k, v in (wc.get("overrides") or {}).items() if v}}


async def _listeners(server: Server, conn: Connection) -> dict[int, set[str]]:
    """Which processes listen on 80/443 (ss needs root to show process names)."""
    out = (await conn.run(sudo(server, "ss -ltnpH"), check=False)).stdout
    found: dict[int, set[str]] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        port = parts[3].rsplit(":", 1)[-1]
        if port in ("80", "443"):
            m = re.search(r'users:\(\("([^"]+)"', line)
            found.setdefault(int(port), set()).add(m.group(1) if m else "unknown")
    return found


async def _inspect(server: Server, conn: Connection, names: list[str]) -> list[dict]:
    if not names:
        return []
    r = await conn.run(sudo(server, "docker inspect " + " ".join(q(n) for n in names)), check=False)
    try:
        data = json.loads(r.stdout or "[]")
    except ValueError:
        return []
    return data if isinstance(data, list) else []


def _traefik_settings(traefik: dict, others: list[dict]) -> dict:
    """Reads Traefik's CLI flags, and the labels the server's other routed containers use, to learn its network,
    HTTPS entrypoint and certificate resolver. Flags are case-insensitive in Traefik (entryPoints == entrypoints)."""
    args = [*(traefik.get("Args") or []), *((traefik.get("Config") or {}).get("Cmd") or [])]
    eps: dict[str, str] = {}
    resolvers: list[str] = []
    net = None
    for a in args:
        if m := re.match(r"--entrypoints\.([^.=]+)\.address=(\S+)", a, re.I):
            eps[m.group(1)] = m.group(2)
        elif m := re.match(r"--certificatesresolvers\.([^.=]+)\.", a, re.I):
            resolvers.append(m.group(1))
        elif m := re.match(r"--providers\.docker\.network=(\S+)", a, re.I):
            net = m.group(1)
    votes: dict[str, Counter] = {"entrypoint": Counter(), "certresolver": Counter(), "network": Counter()}
    for c in others:
        for k, v in ((c.get("Config") or {}).get("Labels") or {}).items():
            if re.fullmatch(r"traefik\.http\.routers\.[^.]+\.entrypoints", k):
                votes["entrypoint"].update(x.strip() for x in v.split(",") if x.strip())
            elif re.fullmatch(r"traefik\.http\.routers\.[^.]+\.tls\.certresolver", k):
                votes["certresolver"][v] += 1
            elif k == "traefik.docker.network":
                votes["network"][v] += 1

    def top(name):
        return votes[name].most_common(1)[0][0] if votes[name] else None

    https_ep = next((n for n, addr in eps.items() if addr.endswith(":443")), None)
    http_ep = next((n for n, addr in eps.items() if addr.endswith(":80")), None)
    tnets = [n for n in ((traefik.get("NetworkSettings") or {}).get("Networks") or {}) if n not in ("bridge", "host", "none")]
    cfg = {"container": (traefik.get("Name") or "").lstrip("/"),
           "network": net or top("network") or (tnets[0] if len(tnets) == 1 else None),
           "entrypoint": https_ep or top("entrypoint"),
           "http_entrypoint": http_ep,
           "certresolver": top("certresolver") or (resolvers[0] if len(set(resolvers)) == 1 else None),
           "networks": tnets, "entrypoints": sorted(eps), "certresolvers": sorted(set(resolvers)),
           "routed_containers": sum(1 for c in others if ((c.get("Config") or {}).get("Labels") or {}).get("traefik.enable") == "true")}
    return {k: v for k, v in cfg.items() if v is not None and (not isinstance(v, str) or k == "container" or NAME_RE.match(v))}


async def detect_web_stack(server: Server, conn: Connection) -> dict:
    """{web_server: caddy|traefik|<owner>, conflict: bool, detected: {...}} - read-only."""
    listeners = await _listeners(server, conn)
    owners = set().union(*listeners.values()) if listeners else set()
    traefik = None
    if (await conn.run("command -v docker", check=False)).exit_status == 0:
        ps = (await conn.run(sudo(server, "docker ps --format " + q("{{.Names}}|{{.Image}}")), check=False)).stdout
        rows = [line.split("|", 1) for line in ps.splitlines() if "|" in line]
        tname = next((n for n, img in rows if re.search(r"(^|/)traefik(:|$)", img)), None)
        if tname:
            infos = await _inspect(server, conn, [n for n, _ in rows])
            t = next((c for c in infos if (c.get("Name") or "").lstrip("/") == tname), None)
            if t:
                traefik = _traefik_settings(t, [c for c in infos if c is not t])
    if traefik and owners <= {"docker-proxy", "traefik"}:
        return {"web_server": "traefik", "conflict": False, "detected": traefik}
    if owners <= {"caddy"}:  # free ports (Caddy will be installed) or our/an existing Caddy
        return {"web_server": "caddy" if owners else None, "conflict": False, "detected": {}}
    owner = ", ".join(sorted("a Docker container" if o == "docker-proxy" else o for o in owners))
    return {"web_server": owner[:40], "conflict": True, "detected": {}}


def _store_detection(server: Server, det: dict) -> None:
    overrides = (server.web_config or {}).get("overrides") or {}
    _update(server.id, web_server=det["web_server"], web_config={"detected": det["detected"], "overrides": overrides, "conflict": det["conflict"]})


# ---------------------------------------------------------------------- operations
async def test_connection(server_id: str) -> dict:
    try:
        server, conn = await open_server(server_id)
        async with conn:
            os_rel = (await conn.run("cat /etc/os-release", check=False)).stdout
            pretty = re.search(r'PRETTY_NAME="?([^"\n]+)', os_rel)
            uname = (await conn.run("uname -sr", check=False)).stdout.strip()
            sudo_ok = server.username == "root" or server.simulated or (await conn.run("sudo -n true", check=False)).exit_status == 0
            det = await detect_web_stack(server, conn) if sudo_ok else {"web_server": None, "conflict": False, "detected": {}}
        if sudo_ok:
            _store_detection(server, det)
        info = {"os": pretty.group(1) if pretty else uname, "kernel": uname, "sudo": sudo_ok, "web_server": det["web_server"],
                "web_conflict": det["conflict"], "traefik": det["detected"] or None}
        _update(server_id, status=("ready" if server.status == "ready" else "ok") if sudo_ok else "error", os_info=info["os"][:200],
                error=None if sudo_ok else "The SSH user needs passwordless sudo", last_checked_at=utcnow())
        return {"ok": sudo_ok, **info}
    except PipelineError as e:
        _update(server_id, status="error", error=e.message, last_checked_at=utcnow())
        return {"ok": False, "error": e.message, "hint": e.hint}


async def provision(server_id: str, log: LogFn = _nolog) -> dict:
    """Prepares the server for websites. Looks at who owns ports 80/443 first:
    an existing Traefik is reused (nothing installed); otherwise Caddy is installed (Debian/Ubuntu).
    Refuses to touch a server whose ports belong to another web server. Safe to run repeatedly."""
    _update(server_id, status="provisioning", error=None)
    try:
        server, conn = await open_server(server_id)
        async with conn:
            await log(f"Connected to {server.host}")
            det = await detect_web_stack(server, conn)
            _store_detection(server, det)
            if det["conflict"]:
                raise ConfigurationError(f"Ports 80/443 on {server.name} are already used by {det['web_server']}",
                                         hint="SiteForge won't install a second web server next to it. Supported: servers running Traefik "
                                              "(detected automatically) or servers with ports 80/443 free.")
            await conn.run(sudo(server, f"mkdir -p {q(server.base_dir + '/sites')}"))
            if server.username != "root" and not server.simulated:
                await conn.run(sudo(server, f"chown -R {q(server.username)} {q(server.base_dir)}"))
            if det["web_server"] == "traefik":
                server.web_config = {"detected": det["detected"], "overrides": (server.web_config or {}).get("overrides") or {}}
                cfg = web_config(server)
                await log(f"Existing Traefik found (container {cfg.get('container')}, {cfg.get('routed_containers', 0)} routed containers) - reusing it")
                missing = [k for k in ("network", "entrypoint") if not cfg.get(k)]
                if missing:
                    raise ConfigurationError(f"Couldn't detect Traefik's {' and '.join(missing)}",
                                             hint="Set them under Servers > Traefik settings, then run Prepare again.")
                if (await conn.run(sudo(server, f"docker network inspect {q(cfg['network'])}"), check=False)).exit_status != 0:
                    raise ConfigurationError(f"Docker network {cfg['network']} doesn't exist on {server.name}",
                                             hint="Correct the network under Servers > Traefik settings.")
                await log(f"Websites will join network {cfg['network']}, entrypoint {cfg['entrypoint']}"
                          + (f", certificates from resolver {cfg['certresolver']}" if cfg.get("certresolver") else " (no certificate resolver found)"))
                await conn.run(sudo(server, f"docker pull -q {SITE_IMAGE}"))
                await log("Server ready - no existing site or container was changed")
                _update(server_id, status="ready", error=None, last_checked_at=utcnow())
                return {"ok": True, "ipv4": server_ip(server), "web_server": "traefik"}
            if (await conn.run("command -v caddy", check=False)).exit_status != 0:
                if (await conn.run("command -v apt-get", check=False)).exit_status != 0:
                    raise ConfigurationError("Automatic setup supports Debian/Ubuntu servers", hint="Install Caddy manually, then run Prepare again.")
                await log("Installing Caddy web server (automatic HTTPS)…")
                await conn.run(sudo(server, "apt-get update -qq"))
                await conn.run(sudo(server, "env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq caddy"))
            await conn.run(sudo(server, f"mkdir -p {CADDY_DIR}"))
            if (await conn.run(f"grep -qF {q(IMPORT_LINE)} {CADDY_MAIN}", check=False)).exit_status != 0:
                await conn.run(sudo(server, f"tee -a {CADDY_MAIN}"), stdin=f"\n{IMPORT_LINE}\n")
            await conn.run(sudo(server, f"caddy validate --config {CADDY_MAIN} --adapter caddyfile"))
            await conn.run(sudo(server, "systemctl enable --now caddy"))
            await conn.run(sudo(server, "systemctl reload caddy"))
            await log("Web server ready")
        _update(server_id, status="ready", web_server="caddy", error=None, last_checked_at=utcnow())
        return {"ok": True, "ipv4": server_ip(server)}
    except PipelineError as e:
        _update(server_id, status="error", error=e.message, last_checked_at=utcnow())
        raise


def _parse_metrics(load: str, nproc: str, free: str, df: str) -> dict:
    m: dict = {}
    try:
        m["load1"] = float(load.split()[0])
        m["cpus"] = int(nproc.strip() or 1)
        m["cpu_percent"] = round(min(100.0, m["load1"] / m["cpus"] * 100), 1)
        mem = next(line.split() for line in free.splitlines() if line.startswith("Mem:"))
        m["mem_total"], m["mem_used"] = int(mem[1]), int(mem[2])
        m["mem_percent"] = round(m["mem_used"] * 100 / max(1, m["mem_total"]), 1)
        disk = df.strip().splitlines()[-1].split()
        m["disk_total"], m["disk_used"] = int(disk[1]), int(disk[2])
        m["disk_percent"] = round(m["disk_used"] * 100 / max(1, m["disk_total"]), 1)
    except (ValueError, IndexError, StopIteration):
        m["parse_error"] = True
    return m


async def refresh_metrics(server_id: str) -> dict:
    try:
        server, conn = await open_server(server_id)
        async with conn:
            load = (await conn.run("cat /proc/loadavg")).stdout
            nproc = (await conn.run("nproc")).stdout
            free = (await conn.run("free -b")).stdout
            df = (await conn.run(f"df -PB1 {q(server.base_dir)}", check=False)).stdout or (await conn.run("df -PB1 /")).stdout
        metrics = {**_parse_metrics(load, nproc, free, df), "checked_at": utcnow().isoformat()}
        _update(server_id, metrics=metrics, last_checked_at=utcnow(), error=None,
                status=server.status if server.status in ("ready", "ok") else "ok")
        return metrics
    except PipelineError as e:
        _update(server_id, status="error", error=e.message, last_checked_at=utcnow())
        raise


def container_name(slug: str) -> str:
    return f"siteforge-{slug}"


def traefik_labels(cfg: dict, slug: str, host: str) -> dict[str, str]:
    r = f"siteforge-{slug}"
    labels = {"siteforge.managed": "true", "siteforge.site": slug, "siteforge.host": host, "traefik.enable": "true",
              f"traefik.http.routers.{r}.rule": f"Host(`{host}`)", f"traefik.http.routers.{r}.entrypoints": cfg["entrypoint"],
              f"traefik.http.routers.{r}.tls": "true", f"traefik.http.services.{r}.loadbalancer.server.port": "80",
              "traefik.docker.network": cfg["network"]}
    if cfg.get("certresolver"):
        labels[f"traefik.http.routers.{r}.tls.certresolver"] = cfg["certresolver"]
    return labels


async def _deploy_container(server: Server, conn: Connection, slug: str, host: str, log: LogFn) -> str:
    """Runs (or keeps) the website's container behind Traefik. The container serves <base>/sites/<slug>/current,
    so later releases and rollbacks are just a symlink switch - the container is only recreated when its routing changes."""
    cfg = web_config(server)
    base = site_dir(server, slug)
    name = container_name(slug)
    labels = traefik_labels(cfg, slug, host)
    await conn.run(f"tee {q(base + '/Caddyfile')}",
                   stdin="{\n\tadmin off\n\tauto_https off\n}\n" + caddy_block(server, slug, host, True, address=":80"))
    existing = await _inspect(server, conn, [name])
    if existing:
        c = existing[0]
        have = (c.get("Config") or {}).get("Labels") or {}
        if have.get("siteforge.managed") != "true":
            raise ConfigurationError(f"A container named {name} already exists on {server.name} and isn't managed by SiteForge",
                                     hint="Rename or remove that container, then publish again.")
        if have == labels and (c.get("State") or {}).get("Running"):
            await log(f"Container {name} already routed for {host} - switched to the new release")
            return name
        await conn.run(sudo(server, f"docker rm -f {q(name)}"))
    parts = ["docker", "run", "-d", "--name", name, "--restart", "unless-stopped", "--network", cfg["network"],
             "--memory", "64m", "--cpus", "0.25", "--read-only", "--tmpfs", "/data", "--tmpfs", "/config",
             "--log-opt", "max-size=5m", "-v", f"{base}:{base}:ro"]
    for k, v in labels.items():
        parts += ["--label", f"{k}={v}"]
    parts += [SITE_IMAGE, "caddy", "run", "--config", f"{base}/Caddyfile", "--adapter", "caddyfile"]
    await conn.run(sudo(server, " ".join(q(p) for p in parts)))
    await log(f"Container {name} started; Traefik routes {host} to it" + (f" (TLS via {cfg['certresolver']})" if cfg.get("certresolver") else ""))
    return name


async def deploy_site(server_id: str, slug: str, domain: str | None, build_dir: Path, version: int, log: LogFn = _nolog) -> dict:
    server, conn = await open_server(server_id)
    base = site_dir(server, slug)
    release = f"{base}/releases/v{version}"
    host = site_host(server, slug, domain)
    if server.web_server == "traefik" and not domain:
        raise ConfigurationError(f"{server.name} serves websites through Traefik, which needs a domain", hint="Add a domain in the Publish dialog.")
    async with conn:
        await conn.run(f"mkdir -p {q(base + '/releases')}")
        await log(f"Uploading release v{version} to {server.name}")
        files = await conn.upload_dir(build_dir, release)
        await log(f"{files} files uploaded")
        await conn.run(f"ln -sfn {q(release)} {q(base + '/current')}")  # atomic switch
        if server.web_server == "traefik":
            container = await _deploy_container(server, conn, slug, host, log)
            await _prune(conn, base)
            return {"release": release, "host": host, "server_id": server_id, "files": files, "container": container, "web_server": "traefik"}
        conf = f"{CADDY_DIR}/{slug}.caddy"
        await conn.run(sudo(server, f"tee {q(conf)}"), stdin=caddy_block(server, slug, host, https=bool(domain)))
        check = await conn.run(sudo(server, f"caddy validate --config {CADDY_MAIN} --adapter caddyfile"), check=False)
        if check.exit_status != 0:
            await conn.run(sudo(server, f"rm -f {q(conf)}"), check=False)
            raise PipelineError("Web server rejected the site configuration", code="caddy_invalid", details={"stderr": check.stderr[-600:]})
        await conn.run(sudo(server, "systemctl reload caddy"))
        await log(f"{host} is served by {server.name}")
        await _prune(conn, base)
    return {"release": release, "host": host, "server_id": server_id, "files": files}


async def _prune(conn: Connection, base: str) -> None:
    releases = sorted((await conn.run(f"ls -1 {q(base + '/releases')}", check=False)).stdout.split(), key=lambda r: int(r.lstrip("v") or 0))
    for old in releases[:-KEEP_RELEASES]:
        await conn.run(f"rm -rf {q(base + '/releases/' + old)}", check=False)


async def activate_release(server_id: str, slug: str, release: str) -> None:
    server, conn = await open_server(server_id)
    base = site_dir(server, slug)
    if not release.startswith(base + "/releases/"):
        raise PipelineError("Release does not belong to this site", code="invalid_release")
    async with conn:
        if (await conn.run(f"ls -1 {q(release)}", check=False)).exit_status != 0:
            raise PipelineError("That release was pruned from the server", code="release_missing", hint="Only the last 5 releases are kept; redeploy instead.")
        await conn.run(f"ln -sfn {q(release)} {q(base + '/current')}")
        if server.web_server != "traefik":  # the site container reads `current` on every request
            await conn.run(sudo(server, "systemctl reload caddy"))


def _code(r) -> int:
    try:
        return int(r.stdout.strip()[-3:])
    except ValueError:
        return 0


async def verify_on_server(server_id: str, host: str) -> int:
    """Requests the site from the server itself (works before DNS has propagated)."""
    server, conn = await open_server(server_id)
    async with conn:
        if server.web_server != "traefik":
            return _code(await conn.run(f"curl -s -o /dev/null -w %{{http_code}} -H {q('Host: ' + host)} http://127.0.0.1/", check=False))
        # through Traefik's HTTPS entrypoint; -k because the certificate may still be being issued
        code = 0
        for _ in range(8):  # Traefik picks up new containers within a few seconds
            for ip in dict.fromkeys(("127.0.0.1", server_ip(server) or "127.0.0.1")):
                code = _code(await conn.run(f"curl -sk -o /dev/null -w %{{http_code}} --max-time 10 --resolve {q(f'{host}:443:{ip}')} "
                                            f"{q(f'https://{host}/')}", check=False))
                if code:
                    break
            if code == 200 or server.simulated:
                return code
            await asyncio.sleep(2)
        return code


async def reload_web_server(server_id: str) -> str:
    server, conn = await open_server(server_id)
    async with conn:
        if server.web_server == "traefik":
            return f"Nothing to reload on {server.name}: Traefik picks up changes automatically"
        await conn.run(sudo(server, "systemctl reload caddy"))
    return f"Web server reloaded on {server.name}"


async def restart_site(server_id: str, slug: str) -> str:
    server, conn = await open_server(server_id)
    async with conn:
        if server.web_server == "traefik":
            await conn.run(sudo(server, f"docker restart {q(container_name(slug))}"))
            return f"Container {container_name(slug)} restarted on {server.name}"
        await conn.run(sudo(server, "systemctl reload caddy"))
    return f"Web server reloaded on {server.name}"


async def remove_site(server_id: str, slug: str) -> None:
    server, conn = await open_server(server_id)
    async with conn:
        if server.web_server == "traefik":
            info = await _inspect(server, conn, [container_name(slug)])
            if info and ((info[0].get("Config") or {}).get("Labels") or {}).get("siteforge.managed") == "true":
                await conn.run(sudo(server, f"docker rm -f {q(container_name(slug))}"), check=False)
        else:
            await conn.run(sudo(server, f"rm -f {q(CADDY_DIR + '/' + slug + '.caddy')}"), check=False)
            await conn.run(sudo(server, "systemctl reload caddy"), check=False)
        await conn.run(f"rm -rf {q(site_dir(server, slug))}", check=False)
