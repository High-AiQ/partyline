"""The server's side of the docker bridge (``docker_bridge``).

When the relay's own connect to the host Docker socket is refused for want of
the docker group, the server starts one bridge under ``sg docker`` and routes
every relay through it. The bridge socket lives outside the relay root and is
hidden from fenced processes; only the server uses it.
"""

from __future__ import annotations

import asyncio
import collections
import contextlib
import errno
import logging
import os
import shlex
import shutil
import sys
import time

logger = logging.getLogger(__name__)
BRIDGE_ROOT = os.path.expanduser("~/.partyline/docker-bridge")
SG = "sg"
ATTEMPTS = 3
WINDOW = 300.0
SOCKET_WAIT = 5.0
REFUSED = (errno.EACCES, errno.EPERM)


def ensure_root() -> str:
    os.makedirs(BRIDGE_ROOT, mode=0o700, exist_ok=True)
    os.chmod(BRIDGE_ROOT, 0o700)
    return BRIDGE_ROOT


class Bridge:
    def __init__(self):
        self.proc: asyncio.subprocess.Process | None = None
        self.attempts: list[float] = []
        self.last_error: str | None = None
        self.stderr: collections.deque[str] = collections.deque(maxlen=20)
        self.lock: asyncio.Lock | None = None  # created lazily, inside the running loop

    @property
    def path(self) -> str:
        return os.path.join(BRIDGE_ROOT, "bridge.sock")

    def running(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    def info(self) -> dict:
        return {"running": self.running(), "pid": self.proc.pid if self.running() else None,
                "last_error": self.last_error}

    async def _drain_stderr(self, proc) -> None:
        async for raw in proc.stderr:
            line = raw.decode(errors="replace").rstrip()
            self.stderr.append(line)
            logger.warning("docker bridge: %s", line)

    def _tail(self) -> str:
        return " | ".join(self.stderr) or "no output"

    async def ensure(self, host: str) -> str | None:
        """The bridge socket if a bridge is (now) running, else None with ``last_error`` set."""
        if self.lock is None:
            self.lock = asyncio.Lock()
        async with self.lock:
            if self.running() and os.path.exists(self.path):
                return self.path
            now = time.monotonic()
            self.attempts = [at for at in self.attempts if now - at < WINDOW]
            if len(self.attempts) >= ATTEMPTS:
                self.last_error = (f"gave up after {ATTEMPTS} failed starts in "
                                   f"{int(WINDOW // 60)} minutes: {self._tail()}")
                return None
            sg = shutil.which(SG)
            if sg is None:
                self.last_error = "`sg` is not installed"
                return None
            self.attempts.append(now)
            ensure_root()
            with contextlib.suppress(FileNotFoundError):
                os.unlink(self.path)  # a killed bridge leaves its socket behind
            self.stderr.clear()
            command = shlex.join([sys.executable, "-m", "partyline.docker_bridge", host, self.path])
            self.proc = await asyncio.create_subprocess_exec(
                sg, "docker", "-c", command, stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
                start_new_session=True, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                env={**os.environ, "PARTYLINE_BRIDGE_OWNER": str(os.getpid())})
            drain = asyncio.get_running_loop().create_task(self._drain_stderr(self.proc))
            deadline = time.monotonic() + SOCKET_WAIT
            while time.monotonic() < deadline:
                if os.path.exists(self.path):
                    self.last_error = None
                    return self.path
                if self.proc.returncode is not None:
                    break
                await asyncio.sleep(0.05)
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(drain, 0.5)
            self.last_error = f"bridge did not start (exit {self.proc.returncode}): {self._tail()}"
            await self.terminate()
            return None

    async def terminate(self) -> None:
        proc, self.proc = self.proc, None
        if proc is not None and proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, 15)
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(proc.wait(), 3)


bridge = Bridge()


async def open_upstream(host: str):
    """Connect to Docker: directly, or through the bridge once the direct route is refused."""
    if not bridge.running():
        try:
            return await asyncio.open_unix_connection(host)
        except OSError as exc:
            if exc.errno not in REFUSED:
                raise
            refused = exc
    else:
        refused = None
        try:
            return await asyncio.open_unix_connection(bridge.path)
        except OSError:
            pass
    path = await bridge.ensure(host)
    if path is None:
        code = refused.errno if refused is not None else errno.EIO
        reason = refused.strerror if refused is not None else "bridge unreachable"
        raise OSError(code, f"{reason}; docker bridge: {bridge.last_error}")
    return await asyncio.open_unix_connection(path)
