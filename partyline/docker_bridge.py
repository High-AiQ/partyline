"""The process that holds the docker group: ``python -m partyline.docker_bridge HOST BRIDGE``.

A running partyline server may lack the ``docker`` group its user belongs to
(a systemd user manager keeps the groups it had at login). The server then
starts this module under ``sg docker`` — which needs no password for a member —
and relays through it: a private unix socket, copied byte for byte to the real
Docker socket. It exits when the server that started it is gone.
"""

from __future__ import annotations

import asyncio
import contextlib
import ctypes
import os
import sys

from .docker_relay import _pump

POLL_SECONDS = 2.0


def die_with_parent() -> None:
    """Ask the kernel for SIGTERM when the parent exits (Linux; best effort)."""
    with contextlib.suppress(OSError, AttributeError):
        ctypes.CDLL(None).prctl(1, 15)  # PR_SET_PDEATHSIG, SIGTERM


def owner_alive(owner: int | None, parent: int) -> bool:
    if os.getppid() != parent:
        return False
    if owner is None:
        return True
    try:
        os.kill(owner, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    return True


async def serve(host: str, path: str) -> None:
    parent = os.getppid()
    owner = int(os.environ["PARTYLINE_BRIDGE_OWNER"]) if os.environ.get("PARTYLINE_BRIDGE_OWNER") else None

    # A client that has half-closed leaves the selector, and the upstream protocol
    # holds its reader only by weakref, so while the reply is pending the handler
    # task, readers and writers are an unrooted cycle: one cyclic GC pass collects
    # it and StreamWriter.__del__ closes both sockets. Hold the writers here
    # (docker_relay anchors its clients the same way).
    clients: set[asyncio.StreamWriter] = set()

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        clients.add(writer)
        try:
            try:
                host_reader, host_writer = await asyncio.open_unix_connection(host)
            except OSError as exc:
                print(f"docker bridge: cannot connect to {host}: {exc.strerror}", file=sys.stderr, flush=True)
                writer.close()
                return
            try:
                await asyncio.gather(_pump(reader, host_writer), _pump(host_reader, writer))
            finally:
                for stream in (writer, host_writer):
                    stream.close()
        finally:
            clients.discard(writer)

    directory = os.path.dirname(path)
    os.makedirs(directory, mode=0o700, exist_ok=True)
    os.chmod(directory, 0o700)
    with contextlib.suppress(FileNotFoundError):
        os.unlink(path)
    previous = os.umask(0o177)
    try:
        server = await asyncio.start_unix_server(handle, path=path)
    finally:
        os.umask(previous)
    os.chmod(path, 0o600)
    try:
        while owner_alive(owner, parent):
            await asyncio.sleep(POLL_SECONDS)
    finally:
        server.close()
        with contextlib.suppress(FileNotFoundError):
            os.unlink(path)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m partyline.docker_bridge HOST_SOCKET BRIDGE_SOCKET", file=sys.stderr)
        return 2
    die_with_parent()
    asyncio.run(serve(*argv))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
