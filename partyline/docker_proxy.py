"""The policy proxy a managed line's relay runs instead of copying bytes.

One request per connection: the request is parsed strictly with h11 (anything
malformed closes the connection), judged by ``docker_policy`` and rebuilt from
parsed parts before it reaches the daemon, so what was checked is exactly what
is sent. Container names and short ids are resolved to the full id first, and the
rewritten path carries that id. Replies tell the client ``Connection: close``;
the docker CLI and SDKs simply reconnect. Only an attach or exec start that
passed the rules becomes a raw pump after the daemon's ``101``.
"""

from __future__ import annotations

import asyncio
import contextlib
import http
import json
import logging
import os
from dataclasses import dataclass
from urllib.parse import urlencode

import h11

from . import docker_admission, docker_api
from .docker_bridge_client import open_upstream
from .docker_policy import (
    LABEL_ATTACHMENT, LABEL_CONVERSATION, LABEL_MANAGED, RECREATE, Denied, Route, create_problems,
    limit_problems, list_filters, parse_target, refusals)
from .docker_relay import DEFAULT_SOCKET, _pump, host_socket

logger = logging.getLogger(__name__)
MAX_BODY = 1 << 20
IDLE = 30.0
_lock: tuple[asyncio.AbstractEventLoop, asyncio.Lock] | None = None
PULL_KEYS = {"fromImage", "tag", "platform"}
CREATE_KEYS = {"name", "platform"}


@dataclass
class Request:
    method: str
    target: str
    headers: dict[str, str]
    body: bytes
    trailing: bytes


@dataclass
class Plan:
    target: str
    body: bytes | None = None
    content_type: str = "application/json"


async def read_request(reader: asyncio.StreamReader) -> Request | None:
    """One request through h11; ``None`` when the client closed first, ``Denied`` when oversized."""
    conn = h11.Connection(h11.SERVER, max_incomplete_event_size=64 * 1024)
    head, body = None, bytearray()
    while True:
        event = conn.next_event()
        if event is h11.NEED_DATA:
            data = await asyncio.wait_for(reader.read(65536), IDLE)
            if not data:
                return None
            conn.receive_data(data)
        elif isinstance(event, h11.Request):
            head = event
            names = [name for name, _value in head.headers]
            if head.http_version not in (b"1.0", b"1.1") or (
                    b"content-length" in names and b"transfer-encoding" in names):
                raise h11.RemoteProtocolError("ambiguous or unsupported request framing")
        elif isinstance(event, h11.Data):
            body += event.data
            if len(body) > MAX_BODY:
                raise Denied("request body too large for a managed docker line (rule: body-limit)", 413)
        elif isinstance(event, h11.EndOfMessage) or event is h11.PAUSED:
            break
        elif isinstance(event, h11.ConnectionClosed):
            return None
    return Request(head.method.decode("ascii"), head.target.decode("ascii"),
                   {name.decode(): value.decode("latin-1") for name, value in head.headers},
                   bytes(body), conn.trailing_data[0])


def reply(writer: asyncio.StreamWriter, status: int, message: str) -> None:
    body = json.dumps({"message": message}).encode()
    writer.write(f"HTTP/1.1 {status} {http.HTTPStatus(status).phrase}\r\nContent-Type: application/json\r\n"
                 f"Connection: close\r\nContent-Length: {len(body)}\r\n\r\n".encode() + body)


def admission_lock() -> asyncio.Lock:
    """Admission is serial: two starts cannot both spend the same headroom."""
    global _lock
    loop = asyncio.get_running_loop()
    if _lock is None or _lock[0] is not loop:
        _lock = (loop, asyncio.Lock())
    return _lock[1]


def socket_paths() -> set[str]:
    return {os.path.realpath(DEFAULT_SOCKET), os.path.realpath(host_socket())}


def bind_roots(db, conv_id: str) -> list[str]:
    """Where a managed container may bind-mount from: the line's worktrees and approved write-set paths."""
    from .docker_relay import is_docker_socket
    from .write_set_routes import list_write_grants

    paths = [att["cwd"] for att in db.list_attachments(conv_id) if att.get("cwd")]
    paths += [g["path"] for g in list_write_grants(db, conv_id) if not is_docker_socket(g["path"])]
    return sorted({os.path.realpath(path) for path in paths})


async def inspect(ref: str) -> dict:
    status, info = await docker_api.request("GET", f"/containers/{ref}/json")
    if status == 404 or not isinstance(info, dict):
        raise Denied(f"No such container: {ref}", 404)
    if status != 200:
        raise Denied(f"docker daemon answered {status} to the inspect", 502)
    return info


def owned_labels(info: dict, conv_id: str, ref: str) -> dict:
    labels = (info.get("Config") or {}).get("Labels") or {}
    if labels.get(LABEL_CONVERSATION) != conv_id:
        raise Denied(f"container {ref} is not owned by this line (rule: ownership)")
    return labels


def query_of(route: Route, allowed: set[str] | None = None) -> str:
    if allowed is not None and (extra := {k for k, _ in route.query} - allowed):
        raise Denied(f"query parameter(s) {sorted(extra)} are not allowed here (rule: strict-query)")
    return ("?" + urlencode(route.query)) if route.query else ""


def line_attachment(db, conv_id: str, claimed: str) -> str:
    atts = db.list_attachments(conv_id)
    if any(att["id"] == claimed for att in atts):
        return claimed
    return next((att["id"] for att in atts if att.get("is_lead")), "")


async def plan_create(runtime, conv_id: str, route: Route, req: Request) -> Plan:
    try:
        body = json.loads(req.body or b"null")
    except ValueError as exc:
        raise Denied("create body is not valid JSON", 400) from exc
    problems = create_problems(body, socket_paths(), bind_roots(runtime.db, conv_id))
    if problems:
        raise Denied("container refused: " + "; ".join(problems) + f" — {RECREATE}")
    claimed = (body.get("Labels") or {}).get(LABEL_ATTACHMENT, "")
    body["Labels"] = {**(body.get("Labels") or {}), LABEL_CONVERSATION: conv_id,
                      LABEL_ATTACHMENT: line_attachment(runtime.db, conv_id, claimed), LABEL_MANAGED: "1"}
    await docker_admission.admit_memory(
        runtime.db, body["HostConfig"]["Memory"], await docker_admission.running_managed())
    return Plan(f"{route.prefix}/containers/create{query_of(route, CREATE_KEYS)}", json.dumps(body).encode())


async def check_start(runtime, conv_id: str, info: dict, ref: str) -> None:
    """A container may run only if it is still a compliant managed one and fits admission."""
    labels = owned_labels(info, conv_id, ref)
    host = info.get("HostConfig") or {}
    problems = [] if labels.get(LABEL_MANAGED) == "1" else ["it was not created through the managed path"]
    problems += limit_problems(host, labels) + refusals(host, socket_paths(), bind_roots(runtime.db, conv_id))
    if problems:
        raise Denied(f"container {ref} may not start: " + "; ".join(problems) + f" — {RECREATE}")
    await docker_admission.admit_start(runtime, conv_id, info, await docker_admission.running_managed())


async def plan_container(runtime, conv_id: str, route: Route, req: Request) -> Plan:
    info = await inspect(route.ref)
    owned_labels(info, conv_id, route.ref)
    if route.op in ("start", "restart"):
        if req.body.strip():
            raise Denied("a container start takes no body (rule: strict-body)")
        await check_start(runtime, conv_id, info, route.ref)
    suffix = "" if route.op == "remove" else f"/{route.op}"
    body = req.body if route.op == "exec" else None
    if route.op == "exec":
        _check_exec(body)
    return Plan(f"{route.prefix}/containers/{info['Id']}{suffix}{query_of(route)}", body)


def _check_exec(body: bytes) -> None:
    try:
        parsed = json.loads(body or b"{}")
    except ValueError as exc:
        raise Denied("exec body is not valid JSON", 400) from exc
    if isinstance(parsed, dict) and parsed.get("Privileged"):
        raise Denied("privileged exec is refused (rule: no-privileged)")


async def plan_exec(runtime, conv_id: str, route: Route, req: Request) -> Plan:
    status, exec_info = await docker_api.request("GET", f"/exec/{route.ref}/json")
    if status != 200 or not isinstance(exec_info, dict):
        raise Denied(f"No such exec instance: {route.ref}", 404)
    owned_labels(await inspect(str(exec_info.get("ContainerID", ""))), conv_id, route.ref)
    return Plan(f"{route.prefix}/exec/{route.ref}/{route.op}{query_of(route)}",
                req.body if route.op == "start" else None)


async def decide(runtime, conv_id: str, route: Route, req: Request) -> Plan:
    if route.kind == "open" or route.kind == "image":
        return Plan(req.target)
    if route.kind == "list":
        return Plan(f"{route.prefix}/containers/json?{list_filters(route, conv_id)}")
    if route.kind == "pull":
        if not any(k == "fromImage" for k, _ in route.query):
            raise Denied("image pull needs fromImage (rule: strict-query)")
        return Plan(f"{route.prefix}/images/create{query_of(route, PULL_KEYS)}")
    if route.kind == "create":
        return await plan_create(runtime, conv_id, route, req)
    if route.kind == "container":
        return await plan_container(runtime, conv_id, route, req)
    return await plan_exec(runtime, conv_id, route, req)


def upstream_head(req: Request, route: Route, plan: Plan, upgrade: bool) -> bytes:
    lines = [f"{req.method} {plan.target} HTTP/1.1", "Host: docker",
             "Connection: Upgrade" if upgrade else "Connection: close"]
    if upgrade:
        lines.append("Upgrade: tcp")
    if plan.body is not None:
        lines += [f"Content-Type: {plan.content_type}", f"Content-Length: {len(plan.body)}"]
    if registry := req.headers.get("x-registry-auth"):
        if route.kind == "pull" and "\r" not in registry and "\n" not in registry:
            lines.append(f"X-Registry-Auth: {registry}")
    return ("\r\n".join(lines) + "\r\n\r\n").encode()


async def _until_eof(reader: asyncio.StreamReader) -> None:
    while await reader.read(65536):
        pass  # anything pipelined after the request is dropped, never forwarded


async def forward(reader, writer, req: Request, route: Route, plan: Plan) -> None:
    upgrade = route.upgradable and "upgrade" in req.headers.get("connection", "").lower() \
        and req.headers.get("upgrade", "").lower() == "tcp"
    try:
        up_reader, up_writer = await open_upstream(host_socket())
    except OSError as exc:
        raise Denied(f"partyline docker proxy: cannot reach Docker: {exc}", 502) from exc
    try:
        up_writer.write(upstream_head(req, route, plan, upgrade) + (plan.body or b""))
        await up_writer.drain()
        if upgrade:
            up_writer.write(req.trailing)
            await asyncio.gather(_pump(reader, up_writer), _pump(up_reader, writer))
            return
        watcher = asyncio.ensure_future(_until_eof(reader))  # the client leaving ends a streaming reply
        pump = asyncio.ensure_future(_pump(up_reader, writer))
        await asyncio.wait({watcher, pump}, return_when=asyncio.FIRST_COMPLETED)
        for task in (watcher, pump):
            task.cancel()
    finally:
        up_writer.close()


async def serve(runtime, conv_id: str, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        req = await read_request(reader)
        if req is None:
            return
        try:
            route = parse_target(req.method, req.target)
            admission = (route.kind, route.op) in (("container", "start"), ("container", "restart")) \
                or route.kind == "create"
            async with (admission_lock() if admission else contextlib.nullcontext()):
                try:
                    plan = await decide(runtime, conv_id, route, req)
                except (OSError, TimeoutError) as exc:
                    raise Denied(f"partyline docker proxy: cannot reach Docker: {exc}", 502) from exc
                await forward(reader, writer, req, route, plan)
        except Denied as denied:
            logger.info("docker proxy %s: %s %s denied: %s", conv_id, req.method, req.target, denied.message)
            reply(writer, denied.status, denied.message)
    except (h11.ProtocolError, TimeoutError, OSError, UnicodeDecodeError) as exc:
        logger.info("docker proxy %s: closing connection: %s", conv_id, exc)
    except Denied as denied:  # an oversized body, before any request was judged
        reply(writer, denied.status, denied.message)
    finally:
        with contextlib.suppress(OSError):
            await writer.drain()
        writer.close()
