"""Bodies a managed line sends: parsed strictly, then rebuilt from allowlists.

Docker's Go decoder matches JSON keys without regard to case, so ``{"hostconfig":
{"privileged": true}}`` means what ``HostConfig.Privileged`` means. The proxy never
forwards the client's bytes or dict. ``loads_strict`` refuses keys that collide once
lowercased, and the ``canonical_*`` builders pick known fields case-insensitively and
emit only their canonical names. Anything not on a list is refused, so a field Docker
adds later is closed until someone decides it is safe.
"""

from __future__ import annotations

import json
import os
import re

from .docker_policy import LABEL_GPU_MB, LABEL_MAX_SECONDS, NAME, refuse, refuse_all
from .docker_schema import CREATE, EXEC_CREATE, EXEC_START, FORBIDDEN, VOLUME, rebuild

LR = "limits-required"
SAFE_SECURITY = re.compile(r"^no-new-privileges([:=](true|false))?$")
SHARE = {"NetworkMode": None, "PidMode": ("",), "IpcMode": ("", "private", "shareable", "none"),
         "UTSMode": ("",), "UsernsMode": ("",), "CgroupnsMode": ("", "private")}


def loads_strict(raw: bytes):
    """Parse JSON, refusing any object with two keys that are equal once lowercased."""
    def pairs(items):
        seen = set()
        for key, _value in items:
            if key.lower() in seen:
                raise refuse("malformed-body", f"duplicate JSON key {key!r}: Docker reads keys without "
                             "regard to case", 400)
            seen.add(key.lower())
        return dict(items)

    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
    except (ValueError, RecursionError) as exc:
        raise refuse("malformed-body", f"request body is not valid JSON: {exc}", 400) from exc


def _int(value) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def limit_problems(host: dict, labels: dict, cap: int) -> list[tuple[str, str]]:
    """What a container must declare before it may run (create, and again at start)."""
    memory = _int(host.get("Memory"))
    problems = []
    if memory <= 0:
        problems.append((LR, "HostConfig.Memory must be a RAM cap > 0"))
    elif _int(host.get("MemorySwap")) != memory:
        problems.append((LR, "HostConfig.MemorySwap must equal Memory (no swap)"))
    if _int(host.get("NanoCpus")) <= 0 and _int(host.get("CpuQuota")) <= 0:
        problems.append((LR, "a CPU limit is required (NanoCpus or CpuQuota > 0)"))
    if _int(host.get("PidsLimit")) <= 0:
        problems.append((LR, "HostConfig.PidsLimit must be > 0"))
    seconds = labels.get(LABEL_MAX_SECONDS, "")
    if not (isinstance(seconds, str) and seconds.isdigit() and int(seconds) > 0):
        problems.append((LR, f"label {LABEL_MAX_SECONDS} (maximum lifetime in seconds) is required"))
    elif int(seconds) > cap:
        problems.append(("lifetime-cap", f"label {LABEL_MAX_SECONDS}={seconds} exceeds the host cap "
                         f"of {cap} s"))
    if host.get("DeviceRequests") and not str(labels.get(LABEL_GPU_MB, "")).isdigit():
        problems.append((LR, f"label {LABEL_GPU_MB} (VRAM need in MB) is required with GPU DeviceRequests"))
    return problems


GPU_ID = re.compile(r"^(\d+|GPU-[0-9A-Fa-f-]+|MIG-[0-9A-Za-z/-]+)$")
FREE_NETWORKS = ("", "default", "none")


def _gpu_request(request) -> bool:
    """A plain NVIDIA GPU request: no other driver (CDI injects devices), no options, GPU ids only."""
    return (isinstance(request, dict) and request.get("Driver") in (None, "", "nvidia")
            and not request.get("Options")
            and all(isinstance(i, str) and GPU_ID.match(i) for i in request.get("DeviceIDs") or [])
            and any(isinstance(caps, list) and "gpu" in caps for caps in request.get("Capabilities") or []))


def network_refs(host: dict, networking: dict | None = None, attached: dict | None = None) -> list[str]:
    """Every network a container names, by name or id, that must be resolved through the daemon."""
    refs = []
    mode = str(host.get("NetworkMode") or "")
    if mode not in FREE_NETWORKS and not mode.startswith("container:"):
        refs.append(mode)
    for table in ((networking or {}).get("EndpointsConfig"), attached):
        for name, endpoint in (table or {}).items():
            refs.append(name)
            if isinstance(endpoint, dict) and endpoint.get("NetworkID"):
                refs.append(str(endpoint["NetworkID"]))
    return refs


def _bind_problem(source: str, socket_paths: set[str], roots: list[str]) -> list[tuple[str, str]]:
    real = os.path.realpath(source)
    for sock in socket_paths:
        if real == sock or sock.startswith(real.rstrip("/") + "/"):
            return [("bind-source", f"bind source {source} exposes the Docker socket")]
    norm = os.path.normpath(source)
    root = next((r for r in roots if norm == r or norm.startswith(r.rstrip("/") + "/")), None)
    if root is None:
        return [("bind-source", f"bind source {source} is outside this line's worktrees and approved "
                 "write-set paths (name the real path, not a link to it)")]
    walked = root
    for part in [p for p in norm[len(root):].split("/") if p]:
        walked = os.path.join(walked, part)
        if os.path.islink(walked):
            return [("bind-source", f"bind source {source} passes through the symlink {walked}")]
    return []


def _volume_driver(options) -> list[tuple[str, str]]:
    config = (options or {}).get("DriverConfig") if isinstance(options, dict) else None
    if config and (config.get("Name") not in (None, "", "local") or config.get("Options")):
        return [("volume-driver", "a volume driver or its options on a mount can bind any host path")]
    return []


LOOPBACK = ("127.0.0.1", "::1")


def _port_problems(host: dict) -> list[tuple[str, str]]:
    """Published ports must bind loopback: an empty HostIp is every interface of the host."""
    out = []
    if host.get("PublishAllPorts"):
        out.append(("port-exposure", "PublishAllPorts is refused: it publishes on every interface"))
    for port, bindings in (host.get("PortBindings") or {}).items():
        for binding in bindings or []:
            if (binding or {}).get("HostIp") not in LOOPBACK:
                out.append(("port-exposure", f"port {port} must bind HostIp 127.0.0.1 or ::1, not "
                            f"{(binding or {}).get('HostIp') or 'every interface'}"))
    return out


def host_problems(host: dict, socket_paths: set[str], roots: list[str]) -> list[tuple[str, str]]:
    """Settings a managed container may never carry; read from a create body or an inspect."""
    out: list[tuple[str, str]] = []
    for key in FORBIDDEN:
        if key in ("MaskedPaths", "ReadonlyPaths", "ContainerIDFile"):
            continue  # an inspect fills these in; a create body is held to the empty value below
        if host.get(key):
            out.append(("privileged" if key == "Privileged" else "forbidden-setting", f"{key} is refused"))
    for key, allowed in SHARE.items():
        value = str(host.get(key) or "")
        if allowed is None and (value == "host" or value.startswith("container:")) \
                or allowed is not None and value not in allowed:
            out.append(("host-namespace", f"{key}={value} is refused"))
    log = host.get("LogConfig")
    if isinstance(log, dict) and log.get("Type") not in (None, "", "json-file", "local"):
        out.append(("log-driver", f"LogConfig.Type={log['Type']} is refused: only json-file or local"))
    out += _port_problems(host)
    if host.get("Runtime") not in (None, "", "runc"):
        out.append(("runtime", f"Runtime={host['Runtime']} is refused: GPUs come only through "
                    "DeviceRequests"))
    if host.get("VolumeDriver") not in (None, "", "local"):
        out.append(("volume-driver", "a volume driver can bind any host path"))
    policy = host.get("RestartPolicy")
    if isinstance(policy, dict) and policy.get("Name") not in (None, "", "no"):
        out.append(("restart-policy", "RestartPolicy must be absent or 'no': the daemon would restart it "
                    "without admission"))
    if any(not SAFE_SECURITY.match(str(opt)) for opt in host.get("SecurityOpt") or []):
        out.append(("security-opt", "SecurityOpt: only no-new-privileges is allowed"))
    if not all(_gpu_request(r) for r in host.get("DeviceRequests") or []):
        out.append(("device-request", "only plain NVIDIA GPU DeviceRequests are allowed (driver nvidia or "
                    "empty, no Options, DeviceIDs only GPU indices or UUIDs)"))
    sources = [str(b).split(":")[0] for b in host.get("Binds") or []]
    for mount in host.get("Mounts") or []:
        if not isinstance(mount, dict):
            out.append(("malformed-body", "Mounts must be objects"))
        elif mount.get("Type") == "bind":
            sources.append(str(mount.get("Source", "")))
        elif mount.get("Type") == "volume":
            out += _volume_driver(mount.get("VolumeOptions"))
        elif mount.get("Type") != "tmpfs":
            out.append(("mount-type", f"mount type {mount.get('Type')} is refused"))
    for source in sources:
        if source.startswith("/"):
            out += _bind_problem(source, socket_paths, roots)
    return out


def _endpoint_problems(endpoints: dict) -> list[tuple[str, str]]:
    """The CLI always sends a default ``GwPriority`` and ``DNSNames``; hold them to their types."""
    out = []
    for name, endpoint in endpoints.items():
        if not isinstance(endpoint, dict):
            continue
        if "GwPriority" in endpoint and _int(endpoint["GwPriority"]) != endpoint["GwPriority"]:
            out.append(("malformed-body", f"endpoint {name} GwPriority must be an integer"))
        names = endpoint.get("DNSNames")
        if names is not None and not (isinstance(names, list) and all(
                isinstance(n, str) and re.fullmatch(NAME, n) for n in names)):
            out.append(("malformed-body", f"endpoint {name} DNSNames must be null or a list of short names"))
    return out


def canonical_create(body, socket_paths: set[str], roots: list[str], cap: int):
    """``(fresh body, problems)`` for a container create; the fresh body is all that is forwarded."""
    if not isinstance(body, dict):
        raise refuse("malformed-body", "create needs a JSON object body", 400)
    problems: list[tuple[str, str]] = []
    fresh = rebuild(body, CREATE, "create body", problems)
    host = fresh.get("HostConfig") or {}
    labels = fresh.get("Labels") or {}
    if not fresh.get("Image") or not isinstance(fresh["Image"], str):
        raise refuse("malformed-body", "create needs an Image", 400)
    if not host or not isinstance(labels, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in labels.items()):
        raise refuse("malformed-body", "create needs HostConfig and string Labels", 400)
    for key in ("MaskedPaths", "ReadonlyPaths", "ContainerIDFile"):
        if host.get(key):
            problems.append(("forbidden-setting", f"{key} is refused"))
    if _int(host.get("OomScoreAdj")) < 0:
        problems.append(("forbidden-setting", "a negative OomScoreAdj is refused"))
    env = fresh.get("Env") or []
    if not host.get("DeviceRequests") and any(
            str(e).startswith(("NVIDIA_", "CUDA_VISIBLE_DEVICES")) for e in env if isinstance(e, str)):
        problems.append(("gpu-env", "NVIDIA_*/CUDA_VISIBLE_DEVICES in the request's Env need a GPU "
                         "DeviceRequests entry (GPU admission)"))
    endpoints = (fresh.get("NetworkingConfig") or {}).get("EndpointsConfig") or {}
    if "host" in endpoints:
        problems.append(("host-namespace", "joining the host network is refused"))
    problems += _endpoint_problems(endpoints)
    fresh["HostConfig"], fresh["Labels"] = host, labels
    problems += host_problems(host, socket_paths, roots) + limit_problems(host, labels, cap)
    return fresh, problems


def canonical_exec_create(raw: bytes) -> dict:
    problems: list[tuple[str, str]] = []
    fresh = rebuild(loads_strict(raw or b"{}"), EXEC_CREATE, "exec body", problems) or {}
    if fresh.pop("Privileged", False):
        problems.append(("privileged", "privileged exec is refused"))
    if problems:
        raise refuse_all(problems)
    return fresh


def canonical_exec_start(raw: bytes) -> dict:
    problems: list[tuple[str, str]] = []
    fresh = rebuild(loads_strict(raw or b"{}"), EXEC_START, "exec start body", problems) or {}
    if problems:
        raise refuse_all(problems)
    return fresh


def canonical_volume(raw: bytes) -> dict:
    """Only default-driver volumes: a driver's options (``type=none,o=bind,device=/``) can bind any path."""
    problems: list[tuple[str, str]] = []
    fresh = rebuild(loads_strict(raw), VOLUME, "volume body", problems)
    if not isinstance(fresh, dict):
        raise refuse("malformed-body", "volume body must be a JSON object", 400)
    if fresh.get("Driver") not in (None, "", "local"):
        problems.append(("volume-driver", "only the local volume driver is allowed"))
    if fresh.get("DriverOpts"):
        problems.append(("volume-driver", "volume DriverOpts are refused (a bind or nfs option reaches "
                         "any host path)"))
    if "Name" in fresh and not re.fullmatch(NAME, str(fresh["Name"])):
        problems.append(("malformed-body", "volume Name is not a plain name"))
    if problems:
        raise refuse_all(problems)
    return fresh
