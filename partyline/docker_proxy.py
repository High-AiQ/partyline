"""The policy proxy a managed line's relay runs instead of copying bytes.

One request per connection: the request is parsed strictly with h11 (anything
malformed closes the connection), judged by ``docker_plan`` and rebuilt from parsed
parts before it reaches the daemon, so what was checked is exactly what is sent. Replies
tell the client ``Connection: close``; the docker CLI and SDKs simply reconnect. A call
that hijacks the connection (attach, exec start, the BuildKit session) becomes a raw
pump only after the daemon itself answers ``101`` (or a raw-stream ``200``); any other
answer is relayed and the connection ends.
"""

from __future__ import annotations

import asyncio
import contextlib
import http
import json
import logging
import re

import h11

from . import docker_admission
from .docker_bridge_client import open_upstream
from .docker_plan import Plan, Request, decide
from .docker_policy import Denied, Route, parse_target, refuse
from .docker_relay import _pump, host_socket

logger = logging.getLogger(__name__)
MAX_BODY = 1 << 20
BUILD_MAX = 4 << 30
IDLE = 30.0
REQUEST_DEADLINE = 30.0
BUILD_DEADLINE = 3600.0
MAX_CONNECTIONS = 64
RAW_STREAMS = (b"application/vnd.docker.raw-stream", b"application/vnd.docker.multiplexed-stream")
_open: dict[str, int] = {}


class Incoming:
    """One client request read through h11: the head first, then the body in one piece or in chunks."""

    def __init__(self, reader: asyncio.StreamReader):
        self.reader = reader
        self.conn = h11.Connection(h11.SERVER, max_incomplete_event_size=64 * 1024)

    async def _event(self):
        while (event := self.conn.next_event()) is h11.NEED_DATA:
            self.conn.receive_data(await asyncio.wait_for(self.reader.read(65536), IDLE))
        return event

    async def head(self) -> Request | None:
        """The request line and headers; ``None`` when the client closed first."""
        event = await self._event()
        if not isinstance(event, h11.Request):
            return None
        names = [name for name, _value in event.headers]
        if event.http_version not in (b"1.0", b"1.1") or (
                b"content-length" in names and b"transfer-encoding" in names):
            raise h11.RemoteProtocolError("ambiguous or unsupported request framing")
        pairs = [(name.decode().lower(), value.decode("latin-1")) for name, value in event.headers]
        return Request(event.method.decode("ascii"), event.target.decode("ascii"), dict(pairs), pairs)

    async def chunks(self, cap: int):
        total = 0
        while not isinstance(event := await self._event(), (h11.EndOfMessage, h11.ConnectionClosed)) \
                and event is not h11.PAUSED:
            if isinstance(event, h11.Data):
                total += len(event.data)
                if total > cap:
                    raise refuse("body-too-large", "request body too large for a managed docker line", 413)
                yield bytes(event.data)

    async def body(self, cap: int) -> bytes:
        return b"".join([data async for data in self.chunks(cap)])

    @property
    def trailing(self) -> bytes:
        return self.conn.trailing_data[0]


def reply(writer: asyncio.StreamWriter, status: int, message: str, rules: tuple[str, ...] = ()) -> None:
    body = json.dumps({"message": message, **({"rules": list(rules)} if rules else {})}).encode()
    writer.write(f"HTTP/1.1 {status} {http.HTTPStatus(status).phrase}\r\nContent-Type: application/json\r\n"
                 f"Connection: close\r\nContent-Length: {len(body)}\r\n\r\n".encode() + body)


def upstream_head(req: Request, route: Route, plan: Plan, upgrade: str) -> bytes:
    lines = [f"{req.method} {plan.target} HTTP/1.1", "Host: docker",
             "Connection: Upgrade" if upgrade else "Connection: close"]
    if upgrade:
        lines.append(f"Upgrade: {upgrade}")
    if plan.stream:
        lines.append(f"Content-Type: {req.headers.get('content-type', 'application/x-tar')}")
        lines.append(f"Content-Length: {req.headers['content-length']}" if "content-length" in req.headers
                     else "Transfer-Encoding: chunked")
    elif plan.body is not None:
        lines += [f"Content-Type: {plan.content_type}", f"Content-Length: {len(plan.body)}"]
    for name, value in req.pairs:
        if name.startswith("x-docker-expose-session-") and route.kind == "session" \
                or name == "x-registry-auth" and route.kind == "pull" \
                or name == "x-registry-config" and route.kind == "build":
            lines.append(f"{name}: {value}")
    return ("\r\n".join(lines) + "\r\n\r\n").encode()


async def _until_eof(reader: asyncio.StreamReader) -> None:
    while await reader.read(65536):
        pass  # anything pipelined after the request is dropped, never forwarded


async def _send_build(incoming: Incoming, up_writer: asyncio.StreamWriter, req: Request) -> None:
    chunked = "content-length" not in req.headers
    async with asyncio.timeout(BUILD_DEADLINE):
        async for data in incoming.chunks(BUILD_MAX):
            up_writer.write(b"%x\r\n%b\r\n" % (len(data), data) if chunked else data)
            await up_writer.drain()
    if chunked:
        up_writer.write(b"0\r\n\r\n")
    await up_writer.drain()


async def _response_head(up_reader: asyncio.StreamReader) -> bytes:
    try:
        return await asyncio.wait_for(up_reader.readuntil(b"\r\n\r\n"), IDLE)
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, TimeoutError) as exc:
        raise Denied("partyline docker proxy: Docker did not answer the upgrade", 502) from exc


async def _relay_answer(head: bytes, up_reader, writer) -> None:
    """A refused upgrade: relay the daemon's answer (Content-Length framed, else to EOF), then end."""
    match = re.search(rb"(?im)^content-length:\s*(\d+)", head)
    if match is None:
        await _pump(up_reader, writer)
        return
    with contextlib.suppress(asyncio.IncompleteReadError, TimeoutError):
        writer.write(await asyncio.wait_for(up_reader.readexactly(min(int(match.group(1)), MAX_BODY)), IDLE))


def hijacked(head: bytes) -> bool:
    """Whether the daemon took over the connection: a 101, or a 200 that carries a raw stream."""
    status = head.split(b" ", 2)[1:2]
    lowered = head.lower()
    return status == [b"101"] or status == [b"200"] and any(
        b"content-type: " + kind in lowered for kind in RAW_STREAMS)


async def forward(incoming: Incoming, reader, writer, req: Request, route: Route, plan: Plan) -> None:
    upgrade = route.upgrade if "upgrade" in req.headers.get("connection", "").lower() \
        and req.headers.get("upgrade", "").lower() == route.upgrade else ""
    try:
        up_reader, up_writer = await open_upstream(host_socket())
    except OSError as exc:
        raise Denied(f"partyline docker proxy: cannot reach Docker: {exc}", 502) from exc
    try:
        up_writer.write(upstream_head(req, route, plan, upgrade) + (plan.body or b""))
        await up_writer.drain()
        if plan.stream:
            await _send_build(incoming, up_writer, req)
        if upgrade:
            head = await _response_head(up_reader)  # decide from the daemon's answer, not the request
            writer.write(head)
            await writer.drain()
            if hijacked(head):
                up_writer.write(req.trailing)
                await asyncio.gather(_pump(reader, up_writer), _pump(up_reader, writer))
            else:
                await _relay_answer(head, up_reader, writer)
            return
        watcher = asyncio.ensure_future(_until_eof(reader))  # the client leaving ends a streaming reply
        pump = asyncio.ensure_future(_pump(up_reader, writer))
        await asyncio.wait({watcher, pump}, return_when=asyncio.FIRST_COMPLETED)
        for task in (watcher, pump):
            task.cancel()
    finally:
        up_writer.close()


async def _handle(runtime, conv_id: str, reader, writer, slots: list) -> None:
    incoming = Incoming(reader)
    async with asyncio.timeout(REQUEST_DEADLINE):
        req = await incoming.head()
        if req is None:
            return
        denial, route = None, None
        try:
            route = parse_target(req.method, req.target)
        except Denied as exc:
            denial = exc
        if route is None or route.kind != "build":
            req.body, req.trailing = await incoming.body(MAX_BODY), incoming.trailing
        if denial:
            raise denial
    try:
        plan = await decide(runtime, conv_id, route, req)
    except (OSError, TimeoutError) as exc:
        raise Denied(f"partyline docker proxy: cannot reach Docker: {exc}", 502) from exc
    slots.append(plan.slot)
    await forward(incoming, reader, writer, req, route, plan)


async def serve(runtime, conv_id: str, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    if _open.get(conv_id, 0) >= MAX_CONNECTIONS:
        with contextlib.suppress(TimeoutError, OSError):
            await asyncio.wait_for(reader.read(65536), 1)  # unread input would reset the connection
        reply(writer, 429, f"refused: connection-limit: too many open docker connections on this line "
                           f"(limit {MAX_CONNECTIONS})")
        writer.close()
        return
    _open[conv_id] = _open.get(conv_id, 0) + 1
    slots: list = []
    try:
        await _handle(runtime, conv_id, reader, writer, slots)
    except Denied as denied:
        logger.info("docker proxy %s: denied: %s", conv_id, denied.message)
        reply(writer, denied.status, denied.message, denied.rules)
    except (h11.ProtocolError, TimeoutError, OSError, UnicodeDecodeError) as exc:
        logger.info("docker proxy %s: closing connection: %s", conv_id, exc)
    except Exception:
        logger.exception("docker proxy %s: internal error", conv_id)
        with contextlib.suppress(Exception):
            reply(writer, 500, "partyline docker proxy: internal error")
    finally:
        for slot in slots:
            docker_admission.release(slot)
        _open[conv_id] -= 1
        with contextlib.suppress(Exception):
            await writer.drain()
        writer.close()
