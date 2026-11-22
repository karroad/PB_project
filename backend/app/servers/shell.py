"""MiniShell: executes the small, fixed set of commands the platform sends to servers, against a local
folder that stands in for the server's filesystem.

Used for sandbox ("simulated") servers and by the test-suite's in-process SSH server, so the exact same
command sequence that runs on a real Ubuntu/Debian VPS is exercised end to end without a VPS.
Unknown commands fail with exit code 127 — nothing is ever executed on the host machine.
"""
from __future__ import annotations

import json
import re
import shlex
import shutil
from dataclasses import dataclass
from pathlib import Path

LINK_PREFIX = "SYMLINK:"
DOCKER_STATE = "/var/lib/siteforge-sim/docker.json"   # emulated Docker engine (containers, networks)
EXTRA_LISTENERS = "/etc/siteforge-sim/listeners"      # "80 nginx" lines: other software holding ports
CADDY_ACTIVE = "/run/siteforge-sim/caddy.active"


@dataclass
class Result:
    exit_status: int
    stdout: str = ""
    stderr: str = ""


class MiniShell:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    # ----------------------------------------------------------------- paths
    def p(self, remote: str) -> Path:
        """Map an absolute remote path into the sandbox root (never escapes it)."""
        rel = Path(remote.lstrip("/"))
        target = (self.root / rel).resolve()
        if not target.is_relative_to(self.root.resolve()):
            raise PermissionError(f"path escapes sandbox: {remote}")
        return target

    def resolve_link(self, remote: str) -> Path:
        """Follow emulated symlinks (stored as small marker files so it works on any OS)."""
        path = self.p(remote)
        for _ in range(10):
            if path.is_symlink():
                path = self.p(str(Path(path.readlink()).as_posix()))
            elif path.is_file() and path.stat().st_size < 1024 and path.read_text(errors="ignore").startswith(LINK_PREFIX):
                path = self.p(path.read_text().split(":", 1)[1].strip())
            else:
                break
        return path

    # ----------------------------------------------------------------- exec
    def run(self, command: str, stdin: str = "") -> Result:
        try:
            argv = shlex.split(command)
        except ValueError as e:
            return Result(2, "", f"parse error: {e}")
        if argv[:2] == ["sudo", "-n"]:
            argv = argv[2:]
        if argv and argv[0] == "env":
            argv = [a for a in argv[1:] if "=" not in a]
        if not argv:
            return Result(0)
        handler = getattr(self, "_" + re.sub(r"[^a-z]", "_", argv[0]), None)
        if handler is None:
            return Result(127, "", f"{argv[0]}: command not supported on simulated server")
        try:
            return handler(argv[1:], stdin)
        except PermissionError as e:
            return Result(1, "", str(e))
        except (OSError, IndexError) as e:
            return Result(1, "", f"{argv[0]}: {e}")

    # ----------------------------------------------------------------- commands
    def _true(self, a, i): return Result(0)
    def _id(self, a, i): return Result(0, "0\n")
    def _uname(self, a, i): return Result(0, "Linux 6.8.0-siteforge-sim x86_64\n")
    def _nproc(self, a, i): return Result(0, "2\n")

    def _cat(self, a, i):
        if a[0] == "/etc/os-release":
            return Result(0, 'PRETTY_NAME="Ubuntu 24.04 LTS (simulated)"\nID=ubuntu\n')
        if a[0] == "/proc/loadavg":
            return Result(0, "0.18 0.11 0.07 1/180 4242\n")
        f = self.p(a[0])
        return Result(0, f.read_text()) if f.is_file() else Result(1, "", f"cat: {a[0]}: No such file")

    def _free(self, a, i):
        return Result(0, "               total        used        free      shared  buff/cache   available\n"
                         "Mem:      4096000000  1228800000  2048000000     1000000   819200000  2662400000\n"
                         "Swap:              0           0           0\n")

    def _df(self, a, i):
        # fixed sample numbers: a simulated server must not report the host machine's disk
        total, used = 80_000_000_000, 18_400_000_000
        return Result(0, f"Filesystem 1-blocks Used Available Capacity Mounted on\n/dev/sda1 {total} {used} {total - used} {round(used * 100 / total)}% /\n")

    def _command(self, a, i):  # command -v X
        name = a[-1]
        if name == "caddy":
            return Result(0, "/usr/bin/caddy\n") if self.p("/usr/bin/caddy").exists() else Result(1)
        if name == "docker":
            return Result(0, "/usr/bin/docker\n") if self._dstate() is not None else Result(1)
        return Result(0, f"/usr/bin/{name}\n") if name in {"apt-get", "curl", "systemctl", "tee"} else Result(1)

    def _apt_get(self, a, i):
        if "install" in a and "caddy" in a:
            self.p("/usr/bin").mkdir(parents=True, exist_ok=True)
            self.p("/usr/bin/caddy").write_text("#!/bin/sh\n# simulated caddy\n")
            self.p("/etc/caddy").mkdir(parents=True, exist_ok=True)
            cf = self.p("/etc/caddy/Caddyfile")
            if not cf.exists():
                cf.write_text(":80 {\n\troot * /usr/share/caddy\n\tfile_server\n}\n")
        return Result(0)

    def _mkdir(self, a, i):
        for d in [x for x in a if not x.startswith("-")]:
            self.p(d).mkdir(parents=True, exist_ok=True)
        return Result(0)

    def _chown(self, a, i): return Result(0)
    def _chmod(self, a, i): return Result(0)

    def _ln(self, a, i):  # ln -sfn TARGET LINK
        target, link = [x for x in a if not x.startswith("-")][-2:]
        lp = self.p(link)
        if lp.is_symlink() or lp.is_file():
            lp.unlink()
        lp.parent.mkdir(parents=True, exist_ok=True)
        lp.write_text(LINK_PREFIX + target)
        return Result(0)

    def _rm(self, a, i):
        for x in [x for x in a if not x.startswith("-")]:
            t = self.p(x)
            if t == self.root.resolve():
                return Result(1, "", "refusing to remove root")
            if t.is_dir():
                shutil.rmtree(t)
            elif t.exists():
                t.unlink()
        return Result(0)

    def _ls(self, a, i):
        d = self.p([x for x in a if not x.startswith("-")][-1])
        if not d.is_dir():
            return Result(2, "", "No such directory")
        return Result(0, "".join(n + "\n" for n in sorted(x.name for x in d.iterdir())))

    def _tee(self, a, i):
        append = "-a" in a
        f = self.p([x for x in a if not x.startswith("-")][-1])
        f.parent.mkdir(parents=True, exist_ok=True)
        with f.open("a" if append else "w", encoding="utf-8") as fh:
            fh.write(i)
        return Result(0, i)

    def _grep(self, a, i):  # grep -qF TEXT FILE
        text, f = [x for x in a if not x.startswith("-")][-2:]
        fp = self.p(f)
        return Result(0 if fp.is_file() and text in fp.read_text() else 1)

    def _caddy(self, a, i):
        if not self.p("/usr/bin/caddy").exists():
            return Result(127, "", "caddy: not installed")
        if a and a[0] == "version":
            return Result(0, "v2.8.4 (simulated)\n")
        if a and a[0] == "validate":
            files = [self.p("/etc/caddy/Caddyfile")] + sorted(self.p("/etc/caddy/siteforge").glob("*.caddy")) if self.p("/etc/caddy/siteforge").exists() else [self.p("/etc/caddy/Caddyfile")]
            for f in files:
                t = f.read_text() if f.exists() else ""
                if t.count("{") != t.count("}"):
                    return Result(1, "", f"Error: adapting config: {f.name}: unbalanced braces")
            return Result(0, "Valid configuration\n")
        return Result(1, "", "unsupported caddy subcommand")

    def _systemctl(self, a, i):
        if not self.p("/usr/bin/caddy").exists():
            return Result(5, "", "Unit caddy.service not found.")
        if "enable" in a and "--now" in a:
            self.p(CADDY_ACTIVE).parent.mkdir(parents=True, exist_ok=True)
            self.p(CADDY_ACTIVE).write_text("1")
        return Result(0, "active\n" if "is-active" in a else "")

    # ----------------------------------------------------------------- listeners (ss -ltnpH)
    def _ss(self, a, i):
        rows: list[tuple[int, str]] = []
        st = self._dstate()
        for c in (st or {}).get("containers", {}).values():
            if c["State"]["Running"]:
                rows += [(port, "docker-proxy") for port in c.get("HostPorts", [])]
        if self.p(CADDY_ACTIVE).exists():
            rows += [(80, "caddy"), (443, "caddy")]
        extra = self.p(EXTRA_LISTENERS)
        if extra.is_file():
            rows += [(int(p), n) for p, n in (line.split() for line in extra.read_text().splitlines() if line.strip())]
        rows.append((22, "sshd"))
        return Result(0, "".join(f'LISTEN 0 4096 0.0.0.0:{p} 0.0.0.0:* users:(("{n}",pid={1000 + k},fd=4))\n' for k, (p, n) in enumerate(rows)))

    # ----------------------------------------------------------------- docker (emulated engine)
    def _dstate(self) -> dict | None:
        f = self.p(DOCKER_STATE)
        return json.loads(f.read_text()) if f.is_file() else None

    def _dsave(self, st: dict) -> None:
        self.p(DOCKER_STATE).write_text(json.dumps(st, indent=1))

    @classmethod
    def seed_docker(cls, root: Path, containers: list[dict] | None = None, networks: list[str] | None = None) -> "MiniShell":
        """Give the emulated server a Docker engine with the given containers (see seed_traefik for the shape)."""
        sh = cls(root)
        sh.p(DOCKER_STATE).parent.mkdir(parents=True, exist_ok=True)
        st = {"networks": ["bridge", *(networks or [])], "containers": {}}
        for c in containers or []:
            st["containers"][c["name"]] = {
                "Name": "/" + c["name"], "Args": c.get("args", []), "HostPorts": c.get("ports", []),
                "Config": {"Image": c["image"], "Labels": c.get("labels", {}), "Cmd": c.get("cmd", [])},
                "NetworkSettings": {"Networks": {n: {} for n in c.get("networks", ["bridge"])}}, "State": {"Running": True}}
        sh._dsave(st)
        return sh

    @classmethod
    def seed_traefik(cls, root: Path, network: str = "proxy", resolver: str = "cloudflare") -> "MiniShell":
        """A server like a typical self-hosted stack: Traefik in Docker owns :80/:443 and routes other containers."""
        traefik = {"name": "traefik", "image": "traefik:v3.3", "ports": [80, 443], "networks": [network, "bridge"],
                   "args": ["--providers.docker=true", "--providers.docker.exposedbydefault=false",
                            "--entrypoints.web.address=:80", "--entrypoints.websecure.address=:443",
                            f"--certificatesresolvers.{resolver}.acme.dnschallenge.provider=cloudflare"]}
        app = {"name": "blog-wordpress", "image": "wordpress:6", "networks": [network],
               "labels": {"traefik.enable": "true", "traefik.http.routers.blog.rule": "Host(`blog.example.org`)",
                          "traefik.http.routers.blog.entrypoints": "websecure", "traefik.http.routers.blog.tls.certresolver": resolver,
                          "traefik.docker.network": network}}
        return cls.seed_docker(root, [traefik, app], [network])

    def _docker(self, a, i):
        st = self._dstate()
        if st is None:
            return Result(127, "", "docker: command not found")
        cs = st["containers"]
        sub, rest = (a[0] if a else ""), a[1:]
        if sub == "version":
            return Result(0, "29.4.0\n")
        if sub == "pull":
            return Result(0, f"{rest[-1]}: Pulled (simulated)\n")
        if sub == "ps":
            fmt = rest[rest.index("--format") + 1] if "--format" in rest else "{{.Names}}"
            return Result(0, "".join(fmt.replace("{{.Names}}", n).replace("{{.Image}}", c["Config"]["Image"]) + "\n"
                                     for n, c in cs.items() if c["State"]["Running"]))
        if sub == "network" and rest[:1] == ["inspect"]:
            return Result(0, "[{}]\n") if rest[-1] in st["networks"] else Result(1, "[]\n", f"Error: No such network: {rest[-1]}")
        if sub == "inspect":
            names = [x for x in rest if not x.startswith("-")]
            found = [cs[n] for n in names if n in cs]
            return Result(0 if len(found) == len(names) else 1, json.dumps(found), "" if len(found) == len(names) else "Error: No such object")
        if sub == "rm":
            for n in [x for x in rest if not x.startswith("-")]:
                cs.pop(n, None)
            self._dsave(st)
            return Result(0)
        if sub == "restart":
            n = rest[-1]
            return Result(0, n + "\n") if n in cs else Result(1, "", f"Error: No such container: {n}")
        if sub == "run":
            return self._docker_run(st, rest)
        return Result(1, "", f"docker {sub}: not supported on simulated server")

    def _docker_run(self, st, a):
        valued = {"--name", "--restart", "--network", "--memory", "--cpus", "--tmpfs", "-v", "--volume", "--label", "-l", "--log-opt", "-e", "--env"}
        spec: dict = {"labels": {}, "network": "bridge", "name": None}
        k = 0
        while k < len(a) and a[k].startswith("-"):
            flag = a[k]
            if flag in valued:
                val = a[k + 1]
                if flag in ("--label", "-l"):
                    key, _, v = val.partition("=")
                    spec["labels"][key] = v
                elif flag == "--name":
                    spec["name"] = val
                elif flag == "--network":
                    spec["network"] = val
                k += 2
            else:
                k += 1
        image, cmd = a[k], a[k + 1:]
        name = spec["name"]
        if name in st["containers"]:
            return Result(125, "", f'Conflict. The container name "/{name}" is already in use')
        if spec["network"] not in st["networks"]:
            return Result(125, "", f"network {spec['network']} not found")
        st["containers"][name] = {"Name": "/" + name, "Args": cmd, "HostPorts": [],
                                  "Config": {"Image": image, "Labels": spec["labels"], "Cmd": cmd},
                                  "NetworkSettings": {"Networks": {spec["network"]: {}}}, "State": {"Running": True}}
        self._dsave(st)
        return Result(0, "f" * 64 + "\n")

    def _traefik_route(self, host: str, https: bool) -> str | None:
        """What Traefik would answer for host: '200'/'404' from the routed container, or None if nothing routes it."""
        st = self._dstate()
        for c in (st or {}).get("containers", {}).values():
            labels = c["Config"]["Labels"]
            if not c["State"]["Running"] or labels.get("traefik.enable") != "true":
                continue
            for key, rule in labels.items():
                if key.endswith(".rule") and f"Host(`{host}`)" in rule:
                    router = key[: -len(".rule")]
                    if https != (labels.get(router + ".tls") == "true" or bool(labels.get(router + ".tls.certresolver"))):
                        continue
                    cmd = c["Config"]["Cmd"]
                    conf = self.p(cmd[cmd.index("--config") + 1]) if "--config" in cmd else None
                    m = re.search(r"root \* (\S+)", conf.read_text()) if conf and conf.is_file() else None
                    index = self.resolve_link(m.group(1)) / "index.html" if m else None
                    return "200" if index and index.is_file() else "502"
        return None

    def _curl(self, a, i):
        """curl -s -o /dev/null -w %{http_code} -H 'Host: x' http://127.0.0.1/  → serves from the matching site.
        Also: curl -sk --resolve host:443:127.0.0.1 https://host/  (through an emulated Traefik)."""
        host = next((a[k + 1].split(":", 1)[1].strip() for k, v in enumerate(a) if v == "-H" and a[k + 1].lower().startswith("host:")), "")
        url = next((x for x in a if x.startswith(("http://", "https://"))), "")
        if not host and "--resolve" in a:
            host = a[a.index("--resolve") + 1].split(":", 1)[0]
        if self._dstate() is not None and any(c["HostPorts"] for c in self._dstate()["containers"].values()):
            return Result(0, self._traefik_route(host, url.startswith("https://")) or "404")
        sites = self.p("/etc/caddy/siteforge")
        for f in sorted(sites.glob("*.caddy")) if sites.exists() else []:
            text = f.read_text()
            first = text.strip().split("{", 1)[0].strip().removeprefix("http://").removeprefix("https://")
            if first == host:
                m = re.search(r"root \* (\S+)", text)
                index = self.resolve_link(m.group(1)) / "index.html" if m else None
                return Result(0, "200" if index and index.is_file() else "404")
        return Result(0, "404")
