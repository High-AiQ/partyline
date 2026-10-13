"""Managed docker access: which calls a line may make and what a container must declare.

Pure rules, no I/O. ``docker_proxy`` applies them to each request a managed line
sends through its relay; every refusal names its rule so the docker CLI prints it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode

LABEL_CONVERSATION = "partyline.conversation"
LABEL_ATTACHMENT = "partyline.attachment"
LABEL_TREE = "partyline.tree"
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
    ("GET", "/info"): "open", ("GET", "/images/json"): "open", ("GET", "/volumes"): "open",
    ("GET", "/system/df"): "open", ("GET", "/events"): "events",
    ("GET", "/containers/json"): "list", ("POST", "/images/create"): "pull",
    ("POST", "/containers/create"): "create", ("POST", "/volumes/create"): "volume",
    ("POST", "/build"): "build", ("POST", "/session"): "session", ("POST", "/grpc"): "session",
}
BUILD = {"t", "dockerfile", "buildargs", "labels", "nocache", "rm", "forcerm", "pull", "q", "cachefrom",
         "target", "platform", "version", "session", "networkmode", "memory", "memswap", "cpushares",
         "cpuquota", "cpuperiod", "cpusetcpus", "shmsize", "outputs", "extrahosts", "buildid"}
QUERY = {  # per (kind, op) or kind: the only parameters that are forwarded, everything else is refused
    "open": {"all", "digests", "filters", "type"}, "list": {"all", "limit", "size", "filters"},
    "pull": {"fromImage", "tag", "platform"}, "create": {"name", "platform"}, "build": BUILD,
    "events": {"since", "until", "filters"}, "volume": set(), "session": set(), "image": set(),
    ("container", "json"): {"size"}, ("container", "logs"): {
        "follow", "stdout", "stderr", "since", "until", "timestamps", "tail"},
    ("container", "stats"): {"stream", "one-shot"}, ("container", "top"): {"ps_args"},
    ("container", "wait"): {"condition"}, ("container", "stop"): {"t", "signal"},
    ("container", "restart"): {"t", "signal"}, ("container", "kill"): {"signal"},
    ("container", "start"): {"detachKeys"}, ("container", "remove"): {"v", "force"},
    ("container", "attach"): {"logs", "stream", "stdin", "stdout", "stderr", "detachKeys"},
    ("container", "resize"): {"h", "w"}, ("container", "exec"): set(),
    ("exec", "resize"): {"h", "w"}, ("exec", "start"): set(), ("exec", "json"): set(),
}
UPGRADES = {("container", "attach"): "tcp", ("exec", "start"): "tcp", ("session", ""): "h2c"}


RULES = (  # every stable rule name a refusal can carry; docs/write-fence.md lists them too
    "endpoint-not-allowed", "update-refused", "malformed-path", "query-not-allowed", "malformed-body",
    "body-too-large", "not-owned", "not-managed", "limits-required", "lifetime-cap", "restart-policy",
    "privileged", "host-namespace", "runtime", "default-runtime", "gpu-env", "volume-driver", "bind-source",
    "forbidden-setting", "field-not-allowed", "security-opt", "device-request", "mount-type",
    "build-network", "build-remote", "upgrade-required", "connection-limit", "budget-exceeded", "gpu-busy",
    "gpu-memory", "gpu-unhealthy", "log-driver", "port-exposure", "network-driver")


class Denied(Exception):
    """A refusal: ``message`` reads ``refused: <rule-name>: <detail>``; ``rules`` names every rule hit."""

    def __init__(self, message: str, status: int = 403, rules: tuple[str, ...] = ()):
        super().__init__(message)
        self.status, self.message, self.rules = status, message, rules


def refuse(rule: str, detail: str, status: int = 403) -> Denied:
    return Denied(f"refused: {rule}: {detail}", status, (rule,))


def refuse_all(problems: list[tuple[str, str]], suffix: str = "", status: int = 403) -> Denied:
    """One refusal naming every problem; the first problem's rule leads, the rest are tagged."""
    rules = tuple(dict.fromkeys(rule for rule, _ in problems))
    detail = "; ".join(text if rule == rules[0] else f"{text} [{rule}]" for rule, text in problems)
    return Denied(f"refused: {rules[0]}: {detail}{suffix}", status, rules)


@dataclass
class Route:
    kind: str  # open | events | list | pull | create | volume | build | session | image | container | exec
    prefix: str = ""
    ref: str = ""  # container name/id, image name, or exec id
    op: str = ""
    query: list[tuple[str, str]] = field(default_factory=list)

    path: str = ""

    @property
    def upgrade(self) -> str:
        """The protocol a hijacking call upgrades to ('' when the call never hijacks)."""
        return UPGRADES.get((self.kind, self.op), "")

    @property
    def allowed_query(self) -> set[str]:
        return QUERY.get((self.kind, self.op), QUERY.get(self.kind, set()))


def parse_target(method: str, target: str) -> Route:
    """Classify one request line, or raise ``Denied`` (default-deny)."""
    path, _, raw_query = target.partition("?")
    dotted = any(part in ("", ".", "..") for part in path.split("/")[1:-1])
    if not SAFE_PATH.match(path) or dotted:
        raise refuse("malformed-path", f"{method} {path[:80]} is not a plain docker path")
    prefix = ""
    if match := VERSION.match(path):
        prefix, path = match.group(0), path[match.end():]
    route = _match(method, path)
    if route is None:
        if path.endswith("/update"):
            raise refuse("update-refused", f"{method} {path}: limits cannot be changed in place; "
                         "recreate the container through the managed path")
        raise refuse("endpoint-not-allowed", f"{method} {path} is not allowed on a managed docker line "
                     "(see docs/write-fence.md, Docker access)")
    route.prefix, route.path = prefix, path
    route.query = parse_qsl(raw_query, keep_blank_values=True)
    if extra := {k for k, _ in route.query} - route.allowed_query:
        raise refuse("build-remote" if route.kind == "build" and "remote" in extra else "query-not-allowed",
                     f"query parameter(s) {sorted(extra)} are not allowed on {method} {path}")
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


def narrow_filters(route: Route, tree: str) -> str:
    """The query with ``filters`` forced to this line's tree; a client filter can only narrow it."""
    query = [(k, v) for k, v in route.query if k != "filters"]
    filters: dict = {}
    for key, value in route.query:
        if key == "filters":
            try:
                parsed = json.loads(value)
            except ValueError as exc:
                raise refuse("query-not-allowed", "filters: not valid JSON") from exc
            if not isinstance(parsed, dict) or not all(isinstance(v, (list, dict)) for v in parsed.values()):
                raise refuse("query-not-allowed", "filters: expected an object of lists")
            filters = {k: list(v) for k, v in parsed.items()}
    filters["label"] = [*filters.get("label", []), f"{LABEL_TREE}={tree}"]
    return urlencode([*query, ("filters", json.dumps(filters))])
