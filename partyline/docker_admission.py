"""Admission for managed containers: host memory budget and the GPU slot."""

from __future__ import annotations

import asyncio
import json
from urllib.parse import quote

from . import docker_api
from .docker_gpu import gpu, slots
from .docker_policy import LABEL_GPU_MB, LABEL_MANAGED, Denied, refuse
from .resource_budget import snapshot

GIB = 1024**3
MAX_SECONDS_SETTING = "docker_max_seconds_cap"
DEFAULT_MAX_SECONDS = 24 * 3600
_pending: dict[str, dict] = {}
_lock: tuple[asyncio.AbstractEventLoop, asyncio.Lock] | None = None


def admission_lock() -> asyncio.Lock:
    """Held for the admission decision and recording the slot, never while a request is forwarded."""
    global _lock
    loop = asyncio.get_running_loop()
    if _lock is None or _lock[0] is not loop:
        _lock = (loop, asyncio.Lock())
    return _lock[1]


def max_seconds_cap(db) -> int:
    """The longest ``partyline.max-seconds`` a container may declare (setting, default 24 h)."""
    try:
        return max(1, int(db.get_setting(MAX_SECONDS_SETTING) or DEFAULT_MAX_SECONDS))
    except ValueError:
        return DEFAULT_MAX_SECONDS


def release(slot: str | None) -> None:
    _pending.pop(slot or "", None)


async def running_managed() -> list[dict]:
    """Managed containers running now, read from the daemon: ``id``, ``memory``, ``gpu_mb``."""
    filters = json.dumps({"label": [f"{LABEL_MANAGED}=1"], "status": ["running"]})
    status, items = await docker_api.request("GET", f"/containers/json?filters={quote(filters)}")
    if status != 200 or not isinstance(items, list):
        raise Denied(f"docker daemon answered {status} to the managed container list", 502)

    async def one(item):
        _status, info = await docker_api.request("GET", f"/containers/{item['Id']}/json")
        memory = ((info or {}).get("HostConfig") or {}).get("Memory") or 0
        gpu_mb = (item.get("Labels") or {}).get(LABEL_GPU_MB)
        return {"id": item["Id"], "memory": memory, "gpu_mb": int(gpu_mb) if str(gpu_mb).isdigit() else None}

    live = list(await asyncio.gather(*(one(item) for item in items)))
    return live + [c for c in _pending.values() if c["id"] not in {x["id"] for x in live}]


def _gb(value: int) -> str:
    return f"{value / GIB:.1f} GB"


async def admit_memory(db, extra: int, running: list[dict]) -> None:
    """The CLI reservations, plus running managed caps, plus this cap, must fit the host budget."""
    view = snapshot(db)
    used = sum(c["memory"] for c in running)
    if view["memory_reserved_bytes"] + used + extra > view["memory_budget_bytes"]:
        raise refuse(
            "budget-exceeded",
            f"docker memory budget full: CLI reservations {_gb(view['memory_reserved_bytes'])} + running "
            f"managed containers {_gb(used)} + this container {_gb(extra)} exceed the host budget "
            f"{_gb(view['memory_budget_bytes'])}; stop something or lower the cap", 409)


async def admit_start(runtime, conv_id: str, info: dict) -> str:
    """Admit one start against what is running now; returns the slot to ``release`` once it has run.

    Memory first, then (for GPU containers) the slot, the health check and free VRAM. The
    caller holds ``admission_lock``; the slot is recorded before it is released, so a second
    start sees this one even though the daemon does not list it yet.
    """
    others = [c for c in await running_managed() if c["id"] != info["Id"]]
    host = info.get("HostConfig") or {}
    memory = host.get("Memory") or 0
    await admit_memory(runtime.db, memory, others)
    need = int(((info.get("Config") or {}).get("Labels") or {}).get(LABEL_GPU_MB) or 0)
    if host.get("DeviceRequests"):
        busy = [c for c in others if c["gpu_mb"] is not None]
        if len(busy) >= slots(runtime.db):
            raise refuse("gpu-busy", f"{len(busy)} managed GPU container(s) running "
                         f"(limit {slots(runtime.db)}); wait for one to stop", 409)
        free = await gpu.free_mb(runtime, conv_id)
        if need > free:
            raise refuse("gpu-memory", f"GPU has {free} MB free, this container declares it needs {need} MB",
                         409)
    _pending[info["Id"]] = {"id": info["Id"], "memory": memory,
                            "gpu_mb": need if host.get("DeviceRequests") else None}
    return info["Id"]
