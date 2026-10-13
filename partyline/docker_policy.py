"""Managed docker access: which calls a line may make and what a container must declare.

Pure rules, no I/O. ``docker_proxy`` applies them to each request a managed line
sends through its relay; every refusal names its rule so the docker CLI prints it.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode

LABEL_CONVERSATION = "partyline.conversation"
LABEL_ATTACHMENT = "partyline.attachment"
LABEL_MANAGED = "partyline.managed"
LABEL_MAX_SECONDS = "partyline.max-seconds"
LABEL_GPU_MB = "partyline.gpu-mem-mb"
RECREATE = "recreate it through the managed path (docs/write-fence.md, Docker access)"
VERSION = re.compile(r"^/v[0-9]+\.[0-9]+(?=/)")
NAME = r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}"
IMAGE = r"[A-Za-z0-9][A-Za-z0-9._:/@-]{0,300}"
SAFE_PATH = re.compile(r"^/[A-Za-z0-9_.:/@-]*$")
CONTAINER_OPS = {
    "GET": {"json", "logs", "stats", "top"},
    "POST": {"wait", "stop", "kill", "start", "restart", "attach", "exec", "resize"},
}
SIMPLE = {
    ("GET", "/_ping"): "open", ("HEAD", "/_ping"): "open", ("GET", "/version"): "open",
    ("GET", "/info"): "open", ("GET", "/events"): "open", ("GET", "/images/json"): "open",
    ("GET", "/containers/json"): "list", ("POST", "/images/create"): "pull",
    ("POST", "/containers/create"): "create",
}


class Denied(Exception):
    def __init__(self, message: str, status: int = 403):
        super().__init__(message)
        self.status, self.message = status, message


@dataclass
class Route:
    kind: str  # open | list | pull | create | image | container | exec
    prefix: str = ""
    ref: str = ""  # container name/id, image name, or exec id
    op: str = ""
    query: list[tuple[str, str]] = field(default_factory=list)

    @property
    def upgradable(self) -> bool:
        return (self.kind, self.op) in (("container", "attach"), ("exec", "start"))


def parse_target(method: str, target: str) -> Route:
    """Classify one request line, or raise ``Denied`` (default-deny)."""
    path, _, raw_query = target.partition("?")
    dotted = any(part in ("", ".", "..") for part in path.split("/")[1:-1])
    if not SAFE_PATH.match(path) or dotted:
        raise Denied(f"{method} {path[:80]}: malformed path (rule: strict-path)")
    prefix = ""
    if match := VERSION.match(path):
        prefix, path = match.group(0), path[match.end():]
    route = _match(method, path)
    if route is None:
        raise Denied(f"{method} {path} is not allowed on a managed docker line (rule: default-deny; "
                     "see docs/write-fence.md, Docker access)")
    route.prefix = prefix
    route.query = parse_qsl(raw_query, keep_blank_values=True)
    return route


def _match(method: str, path: str) -> Route | None:
    if kind := SIMPLE.get((method, path)):
        return Route(kind)
    if method == "GET" and (m := re.fullmatch(rf"/images/({IMAGE})/json", path)):
        return Route("image", ref=m.group(1))
    if method == "DELETE" and (m := re.fullmatch(rf"/containers/({NAME})", path)):
        return Route("container", ref=m.group(1), op="remove")
    if m := re.fullmatch(rf"/containers/({NAME})/([a-z]+)", path):
        if m.group(2) in CONTAINER_OPS.get(method, ()):
            return Route("container", ref=m.group(1), op=m.group(2))
    if m := re.fullmatch(r"/exec/([0-9a-f]{12,64})/(start|json|resize)", path):
        if (method == "GET") == (m.group(2) == "json"):
            return Route("exec", ref=m.group(1), op=m.group(2))
    return None


def list_filters(route: Route, conv_id: str) -> str:
    """The query for ``GET /containers/json`` narrowed to this line's containers."""
    query = [(k, v) for k, v in route.query if k != "filters"]
    filters: dict = {}
    for key, value in route.query:
        if key == "filters":
            try:
                parsed = json.loads(value)
            except ValueError as exc:
                raise Denied("containers filters: not valid JSON (rule: strict-query)") from exc
            if not isinstance(parsed, dict):
                raise Denied("containers filters: expected an object (rule: strict-query)")
            filters = {k: list(v) for k, v in parsed.items()}
    filters["label"] = [*filters.get("label", []), f"{LABEL_CONVERSATION}={conv_id}"]
    return urlencode([*query, ("filters", json.dumps(filters))])


def _int(value) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def limit_problems(host: dict, labels: dict) -> list[str]:
    """What a container must declare before it may run (create, and again at start)."""
    memory = _int(host.get("Memory"))
    problems = []
    if memory <= 0:
        problems.append("HostConfig.Memory must be a RAM cap > 0")
    elif _int(host.get("MemorySwap")) != memory:
        problems.append("HostConfig.MemorySwap must equal Memory (no swap)")
    if _int(host.get("NanoCpus")) <= 0 and _int(host.get("CpuQuota")) <= 0:
        problems.append("a CPU limit is required (NanoCpus or CpuQuota > 0)")
    if _int(host.get("PidsLimit")) <= 0:
        problems.append("HostConfig.PidsLimit must be > 0")
    seconds = labels.get(LABEL_MAX_SECONDS, "")
    if not (isinstance(seconds, str) and seconds.isdigit() and int(seconds) > 0):
        problems.append(f"label {LABEL_MAX_SECONDS} (maximum lifetime in seconds) is required")
    if host.get("DeviceRequests") and not str(labels.get(LABEL_GPU_MB, "")).isdigit():
        problems.append(f"label {LABEL_GPU_MB} (VRAM need in MB) is required with GPU DeviceRequests")
    return problems


def _gpu_request(request) -> bool:
    return isinstance(request, dict) and (
        request.get("Driver") == "nvidia" or any("gpu" in caps for caps in request.get("Capabilities") or []))


def refusals(host: dict, socket_paths: set[str], roots: list[str]) -> list[str]:
    """Settings a managed container may never carry."""
    out = ["Privileged is refused"] if host.get("Privileged") else []
    for key, label in (("CapAdd", "added capabilities"), ("Devices", "host devices"),
                       ("DeviceCgroupRules", "device cgroup rules"), ("VolumesFrom", "volumes-from")):
        if host.get(key):
            out.append(f"{label} are refused ({key})")
    for key in ("NetworkMode", "PidMode", "IpcMode", "UTSMode", "UsernsMode", "CgroupnsMode"):
        value = str(host.get(key) or "")
        if value == "host" or value.startswith("container:"):
            out.append(f"{key}={value} is refused")
    if host.get("CgroupParent"):
        out.append("CgroupParent is refused")
    if any("unconfined" in str(opt) for opt in host.get("SecurityOpt") or []):
        out.append("SecurityOpt unconfined is refused")
    for request in host.get("DeviceRequests") or []:
        if not _gpu_request(request):
            out.append("only GPU DeviceRequests are allowed")
    sources = [str(b).split(":")[0] for b in host.get("Binds") or []]
    for mount in host.get("Mounts") or []:
        if mount.get("Type") == "bind":
            sources.append(str(mount.get("Source", "")))
        elif mount.get("Type") not in ("volume", "tmpfs"):
            out.append(f"mount type {mount.get('Type')} is refused")
    for source in sources:
        if source.startswith("/"):
            out.extend(_bind_problem(source, socket_paths, roots))
    return out


def _bind_problem(source: str, socket_paths: set[str], roots: list[str]) -> list[str]:
    real = os.path.realpath(source)
    for sock in socket_paths:
        if real == sock or sock.startswith(real.rstrip("/") + "/"):
            return [f"bind source {source} exposes the Docker socket"]
    if not any(real == root or real.startswith(root.rstrip("/") + "/") for root in roots):
        return [f"bind source {source} is outside this line's worktrees and approved write-set paths"]
    return []


def create_problems(body, socket_paths: set[str], roots: list[str]) -> list[str]:
    """Every reason a create body is refused; empty means it may be created."""
    if not isinstance(body, dict) or not isinstance(body.get("HostConfig"), dict) or not body.get("Image"):
        return ["create needs a JSON body with Image and HostConfig"]
    labels = body.get("Labels") or {}
    if not isinstance(labels, dict):
        return ["Labels must be an object"]
    host = body["HostConfig"]
    return refusals(host, socket_paths, roots) + limit_problems(host, labels)
