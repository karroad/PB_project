"""SSH connectivity for user-managed servers: key handling, host-key pinning, command execution, uploads."""
from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import asyncssh

from ..config import settings
from ..errors import ConfigurationError, PipelineError, RetryableError
from .shell import MiniShell, Result

CONNECT_TIMEOUT = 20
COMMAND_TIMEOUT = 600


# ---------------------------------------------------------------------- keys
def generate_keypair(comment: str = "siteforge") -> tuple[str, str, str]:
    """Returns (private_openssh, public_openssh, fingerprint) for a new ed25519 key."""
    key = asyncssh.generate_private_key("ssh-ed25519", comment=comment)
    return key.export_private_key("openssh").decode(), key.export_public_key("openssh").decode().strip(), key.get_fingerprint("sha256")


def inspect_private_key(private_key: str, passphrase: str | None = None) -> tuple[str, str, str]:
    """Validates a pasted private key. Returns (public_openssh, fingerprint, algorithm)."""
    try:
        key = asyncssh.import_private_key(private_key.strip() + "\n", passphrase or None)
    except asyncssh.KeyImportError as e:
        raise ConfigurationError(f"Invalid private key: {e}", hint="Paste the full key including the BEGIN/END lines (OpenSSH or PEM format).")
    return key.export_public_key("openssh").decode().strip(), key.get_fingerprint("sha256"), key.get_algorithm()


# ---------------------------------------------------------------------- connections
class Connection:
    host_key: str | None = None

    async def run(self, command: str, stdin: str = "", check: bool = True) -> Result:  # pragma: no cover - interface
        raise NotImplementedError

    async def upload_dir(self, local: Path, remote: str) -> int:  # pragma: no cover - interface
        raise NotImplementedError

    async def close(self) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.close()


def _checked(cmd: str, r: Result, check: bool) -> Result:
    if check and r.exit_status != 0:
        raise PipelineError(f"Server command failed ({r.exit_status}): {cmd.split()[0] if not cmd.startswith('sudo') else ' '.join(cmd.split()[:3])}",
                            code="server_command_failed", details={"command": cmd[:300], "stderr": (r.stderr or r.stdout)[-800:]},
                            hint="Check the server's logs, disk space and that the SSH user has passwordless sudo.")
    return r


class SimulatedConnection(Connection):
    """A local folder that behaves like a fresh Ubuntu server (sandbox mode)."""

    def __init__(self, root: Path):
        self.shell = MiniShell(root)
        self.host_key = "ssh-ed25519 SIMULATED-HOST-KEY"

    async def run(self, command, stdin="", check=True):
        return _checked(command, self.shell.run(command, stdin), check)

    async def upload_dir(self, local, remote):
        dest = self.shell.p(remote)
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(local, dest)
        return sum(1 for f in Path(local).rglob("*") if f.is_file())


class SSHConnection(Connection):
    def __init__(self, conn: asyncssh.SSHClientConnection):
        self.conn = conn
        hk = conn.get_server_host_key()
        self.host_key = hk.export_public_key("openssh").decode().strip() if hk else None

    async def run(self, command, stdin="", check=True):
        try:
            r = await asyncio.wait_for(self.conn.run(command, input=stdin or None, check=False), COMMAND_TIMEOUT)
        except asyncio.TimeoutError:
            raise RetryableError(f"Server command timed out: {command[:60]}", code="server_timeout")
        except (asyncssh.Error, OSError) as e:
            raise RetryableError(f"SSH connection lost: {e}", code="ssh_error")
        return _checked(command, Result(r.exit_status if r.exit_status is not None else 255, str(r.stdout or ""), str(r.stderr or "")), check)

    async def upload_dir(self, local, remote):
        local = Path(local)
        count = 0
        try:
            async with self.conn.start_sftp_client() as sftp:
                await sftp.makedirs(remote, exist_ok=True)
                for path in sorted(local.rglob("*")):
                    rel = path.relative_to(local).as_posix()
                    target = f"{remote.rstrip('/')}/{rel}"
                    if path.is_dir():
                        await sftp.makedirs(target, exist_ok=True)
                    else:
                        await sftp.put(str(path), target)
                        count += 1
        except (asyncssh.Error, OSError) as e:
            raise RetryableError(f"Upload over SFTP failed: {e}", code="sftp_error")
        return count

    async def close(self):
        self.conn.close()
        try:
            await asyncio.wait_for(self.conn.wait_closed(), 5)
        except (asyncio.TimeoutError, asyncssh.Error, OSError):
            pass


def sim_root(server_id: str) -> Path:
    return settings.DATA_DIR / "simservers" / server_id


async def connect(server, private_key: str | None, passphrase: str | None = None) -> Connection:
    """Open a connection. The server's host key is pinned on first use and verified afterwards."""
    if server.simulated:
        return SimulatedConnection(sim_root(server.id))
    if not private_key:
        raise ConfigurationError(f"Server {server.name} has no SSH key", hint="Attach an SSH key to the server under Servers.")
    try:
        key = asyncssh.import_private_key(private_key, passphrase or None)
    except asyncssh.KeyImportError as e:
        raise ConfigurationError(f"Stored SSH key can't be loaded: {e}")
    known_hosts = None  # trust on first use; pinned below
    if server.host_key:
        name = server.host if server.port == 22 else f"[{server.host}]:{server.port}"
        known_hosts = asyncssh.import_known_hosts(f"{name} {server.host_key}\n")
    try:
        conn = await asyncio.wait_for(asyncssh.connect(server.host, port=server.port, username=server.username, client_keys=[key],
                                                       known_hosts=known_hosts, agent_path=None, config=None), CONNECT_TIMEOUT)
    except asyncssh.HostKeyNotVerifiable:
        raise PipelineError(f"Host key of {server.host} changed", code="host_key_mismatch",
                            hint="If the server was reinstalled, reset its pinned host key under Servers. Otherwise treat this as a security alert.")
    except asyncssh.PermissionDenied:
        raise ConfigurationError(f"SSH login refused for {server.username}@{server.host}",
                                 hint="Add the key's public key to ~/.ssh/authorized_keys on the server.")
    except asyncio.TimeoutError:
        raise RetryableError(f"Timed out connecting to {server.host}:{server.port}", code="ssh_timeout")
    except (asyncssh.Error, OSError) as e:
        raise RetryableError(f"Can't reach {server.host}:{server.port}: {e}", code="ssh_unreachable")
    return SSHConnection(conn)
