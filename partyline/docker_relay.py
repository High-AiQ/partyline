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
import os
import shutil
import socket

RELAY_ROOT = os.path.expanduser("~/.partyline/docker")
DEFAULT_SOCKET = "/run/docker.sock"
_servers: dict[str, asyncio.Task] = {}


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


def in_use() -> bool:
    """Whether any line currently has a relay directory to hide from the others."""
    try:
        return bool(os.listdir(RELAY_ROOT))
    except OSError:
        return False


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


async def _serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        host_reader, host_writer = await asyncio.open_unix_connection(host_socket())
    except OSError:
        writer.close()
        return
    try:
        await asyncio.gather(_pump(reader, host_writer), _pump(host_reader, writer))
    finally:
        for stream in (writer, host_writer):
            stream.close()


def start(conv_id: str) -> str:
    """Listen for this line (idempotent) and return the socket path; call inside the loop."""
    path = relay_socket(conv_id)
    running = _servers.get(conv_id)
    if running is not None and not running.done():
        return path
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
    # Listening before the server task first runs: early connects queue.
    _servers[conv_id] = asyncio.get_running_loop().create_task(
        asyncio.start_unix_server(_serve, sock=listener))
    return path


async def stop(conv_id: str) -> None:
    task = _servers.pop(conv_id, None)
    if task is not None:
        server = await task
        server.close()
        await server.wait_closed()
    shutil.rmtree(relay_dir(conv_id), ignore_errors=True)


def prepare(att: dict) -> None:
    """At spawn: a line holding the docker grant gets its relay and ``docker_socket``."""
    if any(is_docker_socket(str(g.get("path", ""))) for g in att.get("write_grants") or []):
        att["docker_socket"] = start(att["conv_id"])
