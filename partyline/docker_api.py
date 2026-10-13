"""A minimal Docker Engine API client for the server, over the host socket or the bridge."""

from __future__ import annotations

import asyncio
import json

from .docker_bridge_client import open_upstream
from .docker_relay import host_socket

TIMEOUT = 10.0


def _unchunk(body: bytes) -> bytes:
    out, rest = b"", body
    while rest:
        size, _, rest = rest.partition(b"\r\n")
        try:
            length = int(size.split(b";")[0], 16)
        except ValueError:
            break
        if length == 0:
            break
        out, rest = out + rest[:length], rest[length + 2:]
    return out


async def request(method: str, path: str, *, timeout: float = TIMEOUT) -> tuple[int, object]:
    """One HTTP/1.0 call to the daemon: ``(status, decoded JSON or None)``. Raises OSError/TimeoutError."""
    _reader, writer = await asyncio.wait_for(open_upstream(host_socket()), timeout)
    try:
        writer.write(f"{method} {path} HTTP/1.0\r\nHost: docker\r\nContent-Length: 0\r\n\r\n".encode())
        await writer.drain()
        raw = await asyncio.wait_for(_reader.read(-1), timeout)
    finally:
        writer.close()
    head, _, body = raw.partition(b"\r\n\r\n")
    if b"transfer-encoding: chunked" in head.lower():
        body = _unchunk(body)
    try:
        status = int(head.split(b" ", 2)[1])
    except (IndexError, ValueError) as exc:
        raise OSError(f"docker daemon sent no HTTP status: {head[:80]!r}") from exc
    try:
        return status, json.loads(body) if body.strip() else None
    except ValueError:
        return status, None
