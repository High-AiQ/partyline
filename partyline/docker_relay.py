"""Docker access for a fenced line, relayed from the server.

Inside the fence's user namespace the Docker socket's group is unmapped
(unprivileged bubblewrap maps only our own uid and gid), so every connect
fails with EACCES and no write-set grant can fix that. The server runs outside
the fence and holds the group, so it relays: per granted line, a unix socket
at ``~/.partyline/docker/<conv_id>/docker.sock`` — owned by our uid, mapped
inside the fence — whose connections are copied to the host socket.

This is root-equivalent access to the host. Only a person may grant it, and
the fence hides every relay directory but the granted line's own.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shutil
import socket
from dataclasses import dataclass, field
from functools import partial

from .docker_bridge_client import bridge, open_upstream

logger = logging.getLogger(__name__)
RELAY_ROOT = os.path.expanduser("~/.partyline/docker")
DEFAULT_SOCKET = "/run/docker.sock"


def host_socket() -> str:
    host = os.environ.get("DOCKER_HOST", "")
    return host[len("unix://"):] if host.startswith("unix://") else DEFAULT_SOCKET


def is_docker_socket(path: str) -> bool:
    """Whether ``path`` resolves to the host Docker socket (through any symlink)."""
    real = os.path.realpath(path)
    return real in {os.path.realpath(DEFAULT_SOCKET), os.path.realpath(host_socket())}


def ensure_root() -> str:
    os.makedirs(RELAY_ROOT, mode=0o700, exist_ok=True)
    os.chmod(RELAY_ROOT, 0o700)
    return RELAY_ROOT


def any_grant(db) -> bool:
    """Whether any live line on the host holds a docker grant (decided from the grant rows)."""
    rows = db._exec(
        "SELECT g.path FROM conversation_write_grants g JOIN conversations c ON c.id=g.conv_id "
        "WHERE c.archived_at IS NULL").fetchall()
    return any(is_docker_socket(row["path"]) for row in rows)


def relay_dir(conv_id: str) -> str:
    return os.path.join(RELAY_ROOT, conv_id)


def relay_socket(conv_id: str) -> str:
    return os.path.join(relay_dir(conv_id), "docker.sock")


async def _pump(source: asyncio.StreamReader, sink: asyncio.StreamWriter) -> None:
    try:
        while data := await source.read(65536):
            sink.write(data)
            await sink.drain()
        if sink.can_write_eof():
            sink.write_eof()
    except OSError:
        pass


def failure_text(host: str, error: OSError) -> str:
    return (f"partyline docker relay: cannot connect to {host}: {error.strerror or error} — the "
            "partyline server process needs the docker group (log out and in, or restart "
            "the user manager, then restart partyline)")


async def probe() -> str | None:
    """Try the host socket once: None when it answers, else the reason it does not."""
    host = host_socket()
    try:
        _reader, writer = await open_upstream(host)
    except OSError as exc:
        return failure_text(host, exc)
    writer.close()
    return None


@dataclass
class Relay:
    path: str
    task: asyncio.Task  # resolves to the asyncio.Server
    clients: set = field(default_factory=set)
    last_error: str | None = None

    def listening(self) -> bool:
        if not self.task.done():
            return True
        return not self.task.cancelled() and self.task.exception() is None \
            and self.task.result().is_serving() and os.path.exists(self.path)


_relays: dict[str, Relay] = {}
_runtime = None


def bind_runtime(runtime) -> None:
    """Let a relay tell its line why it cannot reach Docker."""
    global _runtime
    _runtime = runtime


def relay_mode(conv_id: str) -> str:
    """``unrestricted`` only when the line's docker grant row says so; everything else is managed."""
    if _runtime is None:
        return "managed"
    rows = _runtime.db._exec("SELECT path, docker_mode FROM conversation_write_grants WHERE conv_id=?",
                             (conv_id,)).fetchall()
    return "unrestricted" if any(is_docker_socket(row["path"]) and row["docker_mode"] == "unrestricted"
                                 for row in rows) else "managed"


async def _serve(conv_id: str, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    if relay_mode(conv_id) == "managed":
        from . import docker_proxy
        await docker_proxy.serve(_runtime, conv_id, reader, writer)
        return
    relay = _relays.get(conv_id)
    host = host_socket()
    try:
        host_reader, host_writer = await open_upstream(host)
    except OSError as exc:
        text = failure_text(host, exc)
        logger.warning("docker relay for %s: upstream %s failed: errno %s: %s",
                       conv_id, host, exc.errno, exc.strerror)
        if relay is not None:
            relay.last_error = text
        # Take the request off the wire first: closing with it unread would
        # reset the connection and swallow the reply.
        with contextlib.suppress(TimeoutError, OSError):
            await asyncio.wait_for(reader.read(65536), 1)
        body = text.encode()
        writer.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Type: text/plain\r\n"
                     b"Connection: close\r\nContent-Length: %d\r\n\r\n" % len(body) + body)
        with contextlib.suppress(OSError):
            await writer.drain()
        writer.close()
        return
    if relay is not None:
        relay.last_error = None
        relay.clients.add(writer)
    try:
        await asyncio.gather(_pump(reader, host_writer), _pump(host_reader, writer))
    finally:
        if relay is not None:
            relay.clients.discard(writer)
        for stream in (writer, host_writer):
            stream.close()


async def _announce_probe(conv_id: str) -> None:
    reason = await probe()
    if reason is None:
        return
    logger.warning("docker relay for %s cannot reach Docker: %s", conv_id, reason)
    if conv_id in _relays:
        _relays[conv_id].last_error = reason
    if _runtime is not None:
        from .system_notice import post_system_notice
        await post_system_notice(_runtime, conv_id, f"⚠ docker access cannot work: {reason}")


def start(conv_id: str) -> str:
    """Listen for this line (one listener, reused) and return the socket path; call inside the loop."""
    path = relay_socket(conv_id)
    existing = _relays.get(conv_id)
    if existing is not None and existing.listening():
        return path
    if existing is not None:
        _close_now(existing)
    ensure_root()
    os.makedirs(relay_dir(conv_id), mode=0o700, exist_ok=True)
    os.chmod(relay_dir(conv_id), 0o700)
    with contextlib.suppress(FileNotFoundError):
        os.unlink(path)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    previous = os.umask(0o177)
    try:
        listener.bind(path)
    finally:
        os.umask(previous)
    listener.listen()
    listener.setblocking(False)
    loop = asyncio.get_running_loop()
    # Listening before the server task first runs: early connects queue.
    _relays[conv_id] = Relay(path, loop.create_task(
        asyncio.start_unix_server(partial(_serve, conv_id), sock=listener)))
    loop.create_task(_announce_probe(conv_id))
    return path


def _close_now(relay: Relay) -> None:
    for client in list(relay.clients):
        client.close()
    if relay.task.done() and not relay.task.cancelled() and relay.task.exception() is None:
        relay.task.result().close()
    else:
        relay.task.cancel()


async def stop(conv_id: str) -> None:
    relay = _relays.pop(conv_id, None)
    if relay is not None:
        for client in list(relay.clients):
            client.close()  # wait_closed waits for open connections
        server = await relay.task
        server.close()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(server.wait_closed(), 5)
    shutil.rmtree(relay_dir(conv_id), ignore_errors=True)


async def status() -> list[dict]:
    """Per relay: where it listens, whether it does, who is connected, why it last failed."""
    reason = await probe()
    return [{"conv_id": conv_id, "socket": relay.path, "listening": relay.listening(),
             "connections": len(relay.clients), "last_error": relay.last_error,
             "probe": "ok" if reason is None else reason, "bridge": bridge.info(),
             "mode": relay_mode(conv_id)}
            for conv_id, relay in sorted(_relays.items())]


def prepare(att: dict) -> None:
    """At spawn: a line holding the docker grant gets its relay and ``docker_socket``."""
    if any(is_docker_socket(str(g.get("path", ""))) for g in att.get("write_grants") or []):
        att["docker_socket"] = start(att["conv_id"])
