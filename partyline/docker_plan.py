"""What a managed line's request becomes: ownership, admission and the rebuilt call.

``decide`` turns one parsed request into a ``Plan`` (the path, body and headers that
are forwarded) or raises ``Denied``. Ownership is the line's tree: a container belongs to
its creator's top-level line and any line under that line may operate on it.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from dataclasses import dataclass, field
from urllib.parse import urlencode

from . import docker_admission, docker_api
from .docker_admission import admission_lock, max_seconds_cap
from .docker_body import (
    canonical_create, canonical_exec_create, canonical_exec_start, canonical_volume, host_problems,
    limit_problems, loads_strict, network_refs)
from .docker_policy import (
    LABEL_ATTACHMENT, LABEL_CONVERSATION, LABEL_MANAGED, LABEL_TREE, NAME, RECREATE, Denied, Route,
    narrow_filters, refuse, refuse_all)
from .docker_relay import DEFAULT_SOCKET, host_socket
from .hierarchy import ancestors

RUNTIME_TTL = 60.0
_runtime_seen = (float("-inf"), "runc")
PS_ARGS = re.compile(r"^[A-Za-z0-9 ,=-]*$")


@dataclass
class Request:
    method: str
    target: str
    headers: dict[str, str]
    pairs: list[tuple[str, str]] = field(default_factory=list)
    body: bytes = b""
    trailing: bytes = b""


@dataclass
class Plan:
    target: str
    body: bytes | None = None
    content_type: str = "application/json"
    answer: tuple[int, bytes] | None = None  # a reply built here, sent instead of forwarding
    slot: str | None = None  # admission slot to release once the request has run
    stream: bool = False  # the body is streamed to the daemon, not held (image builds)


def tree_of(db, conv_id: str) -> str:
    lineage = ancestors(db, conv_id)
    return lineage[-1] if lineage else conv_id


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


def owned_tree(info: dict) -> str | None:
    return ((info.get("Config") or {}).get("Labels") or {}).get(LABEL_TREE)


def owned_labels(db, info: dict, conv_id: str, ref: str) -> dict:
    labels = (info.get("Config") or {}).get("Labels") or {}
    if labels.get(LABEL_TREE) != tree_of(db, conv_id):
        raise refuse("not-owned", f"container {ref} is not owned by this line's tree")
    return labels


def query_of(route: Route, pairs: list[tuple[str, str]] | None = None) -> str:
    pairs = route.query if pairs is None else pairs
    return ("?" + urlencode(pairs)) if pairs else ""


def line_attachment(db, conv_id: str, claimed: str) -> str:
    atts = db.list_attachments(conv_id)
    if any(att["id"] == claimed for att in atts):
        return claimed
    return next((att["id"] for att in atts if att.get("is_lead")), "")


def _json(value: dict) -> bytes:
    return json.dumps(value).encode()


SAFE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


async def check_networks(refs: list[str]) -> None:
    """Resolve each named network through the daemon: only bridge-driver networks may be joined."""
    for ref in dict.fromkeys(refs):
        if not SAFE_REF.match(ref):
            raise refuse("network-driver", f"network {ref!r} is not a plain name or id")
        status, info = await docker_api.request("GET", f"/networks/{ref}")
        if status == 404 or not isinstance(info, dict):
            raise refuse("network-driver", f"network {ref} does not resolve")
        if status != 200:
            raise Denied(f"docker daemon answered {status} to the network lookup", 502)
        if info.get("Driver") != "bridge":
            raise refuse("network-driver", f"network {ref} uses the {info.get('Driver')!r} driver; only "
                         "bridge-driver networks (and none or default) may be joined")


async def default_runtime() -> str:
    """The daemon's default runtime, read from ``/info`` and cached briefly."""
    global _runtime_seen
    if time.monotonic() - _runtime_seen[0] > RUNTIME_TTL:
        status, info = await docker_api.request("GET", "/info")
        if status != 200 or not isinstance(info, dict):
            raise Denied(f"docker daemon answered {status} to /info", 502)
        _runtime_seen = (time.monotonic(), str(info.get("DefaultRuntime") or "runc"))
    return _runtime_seen[1]


async def plan_create(runtime, conv_id: str, route: Route, req: Request) -> Plan:
    db = runtime.db
    fresh, problems = canonical_create(
        loads_strict(req.body), socket_paths(), bind_roots(db, conv_id), max_seconds_cap(db))
    if problems:
        raise refuse_all(problems, f" — {RECREATE}")
    if not fresh["HostConfig"].get("DeviceRequests") and (name := await default_runtime()) != "runc":
        raise refuse("default-runtime", f"the daemon's default runtime is {name!r}, not runc: a non-GPU "
                     "container would get GPU access outside admission; ask a person to fix the daemon")
    await check_networks(network_refs(fresh["HostConfig"], fresh.get("NetworkingConfig")))
    labels = fresh["Labels"]
    fresh["Labels"] = {**labels, LABEL_CONVERSATION: conv_id, LABEL_TREE: tree_of(db, conv_id),
                       LABEL_ATTACHMENT: line_attachment(db, conv_id, labels.get(LABEL_ATTACHMENT, "")),
                       LABEL_MANAGED: "1"}
    if any(k == "name" and not re.fullmatch(NAME, v) for k, v in route.query):
        raise refuse("query-not-allowed", "container name is not a plain name")
    return Plan(f"{route.prefix}/containers/create{query_of(route)}", _json(fresh))


def start_problems(runtime, conv_id: str, info: dict, labels: dict) -> list[tuple[str, str]]:
    """Why an existing container may not run: it must still be a compliant managed one."""
    host = info.get("HostConfig") or {}
    problems = [] if labels.get(LABEL_MANAGED) == "1" else [
        ("not-managed", "it was not created through the managed path")]
    return problems + limit_problems(host, labels, max_seconds_cap(runtime.db)) \
        + host_problems(host, socket_paths(), bind_roots(runtime.db, conv_id))


async def plan_container(runtime, conv_id: str, route: Route, req: Request) -> Plan:
    info = await inspect(route.ref)
    labels = owned_labels(runtime.db, info, conv_id, route.ref)
    body, slot = None, None
    if route.op == "exec":
        body = _json(canonical_exec_create(req.body))
    elif req.body.strip():
        raise refuse("malformed-body", f"container {route.op} takes no body")
    if route.op == "top" and not PS_ARGS.match(dict(route.query).get("ps_args", "")):
        raise refuse("query-not-allowed", "top: ps_args may hold only plain options")
    if route.op in ("start", "restart"):
        if problems := start_problems(runtime, conv_id, info, labels):
            raise refuse_all(problems, f" — container {route.ref} may not start; {RECREATE}")
        await check_networks(network_refs(
            info.get("HostConfig") or {}, None, (info.get("NetworkSettings") or {}).get("Networks")))
        async with admission_lock():
            slot = await docker_admission.admit_start(runtime, conv_id, info)
    suffix = "" if route.op == "remove" else f"/{route.op}"
    return Plan(f"{route.prefix}/containers/{info['Id']}{suffix}{query_of(route)}", body, slot=slot)


async def plan_exec(runtime, conv_id: str, route: Route, req: Request) -> Plan:
    status, exec_info = await docker_api.request("GET", f"/exec/{route.ref}/json")
    if status != 200 or not isinstance(exec_info, dict):
        raise Denied(f"No such exec instance: {route.ref}", 404)
    owned_labels(runtime.db, await inspect(str(exec_info.get("ContainerID", ""))), conv_id, route.ref)
    body = None
    if route.op == "start":
        body = _json(canonical_exec_start(req.body))
    elif req.body.strip():
        raise refuse("malformed-body", f"exec {route.op} takes no body")
    return Plan(f"{route.prefix}/exec/{route.ref}/{route.op}{query_of(route)}", body)


async def plan_network(runtime, conv_id: str, route: Route) -> Plan:
    """A network lookup, answered here: only this tree's containers stay in ``Containers``.

    The daemon lists every container attached with its name, IP and MAC, which would show other
    trees' containers; ``Services`` and ``Peers`` are dropped. Anything but a 200 (a missing
    network is the daemon's 404) is passed through as it came.
    """
    status, info = await docker_api.request("GET", f"{route.prefix}/networks/{route.ref}{query_of(route)}")
    if status != 200 or not isinstance(info, dict):
        return Plan("", answer=(status, json.dumps(info if info is not None else {}).encode()))
    tree = tree_of(runtime.db, conv_id)

    async def mine(ref: str) -> bool:
        try:
            return owned_tree(await inspect(ref)) == tree
        except Denied:
            return False  # gone since the lookup, or not readable: not shown

    shown = info.get("Containers") if isinstance(info.get("Containers"), dict) else {}
    keep = await asyncio.gather(*(mine(ref) for ref in shown))
    info = {k: v for k, v in info.items() if k not in ("Services", "Peers")}
    info["Containers"] = {ref: item for (ref, item), ok in zip(shown.items(), keep, strict=True) if ok}
    return Plan("", answer=(200, json.dumps(info).encode()))


async def plan_build(route: Route) -> Plan:
    mode = dict(route.query).get("networkmode", "")
    if mode == "host" or mode.startswith("container:"):
        raise refuse("build-network", f"build networkmode={mode} is refused")
    if mode not in ("", "default", "none"):
        await check_networks([mode])
    return Plan(f"{route.prefix}/build{query_of(route)}", stream=True)


async def decide(runtime, conv_id: str, route: Route, req: Request) -> Plan:
    tree = tree_of(runtime.db, conv_id)
    if route.kind == "network":
        return await plan_network(runtime, conv_id, route)
    if route.kind in ("open", "image", "lookup"):
        return Plan(f"{route.prefix}{route.path}{query_of(route)}")
    if route.kind in ("list", "events"):
        return Plan(f"{route.prefix}{route.path}?{narrow_filters(route, tree)}")
    if route.kind == "pull":
        if not any(k == "fromImage" for k, _ in route.query):
            raise refuse("query-not-allowed", "image pull needs fromImage")
        return Plan(f"{route.prefix}/images/create{query_of(route)}")
    if route.kind == "volume":
        return Plan(f"{route.prefix}/volumes/create", _json(canonical_volume(req.body)))
    if route.kind == "build":
        return await plan_build(route)
    if route.kind == "session":
        if req.headers.get("upgrade", "").lower() != route.upgrade:
            raise refuse("upgrade-required", f"{route.path} is for {route.upgrade} upgrades only")
        return Plan(f"{route.prefix}{route.path}")
    if route.kind == "create":
        return await plan_create(runtime, conv_id, route, req)
    if route.kind == "container":
        return await plan_container(runtime, conv_id, route, req)
    return await plan_exec(runtime, conv_id, route, req)
