"""Admission for managed containers: host memory budget and the GPU slot."""

from __future__ import annotations

import asyncio
import json
from urllib.parse import quote

from . import docker_api
from .docker_gpu import gpu, slots
from .docker_policy import LABEL_GPU_MB, LABEL_MANAGED, Denied
from .resource_budget import snapshot

GIB = 1024**3


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

    return list(await asyncio.gather(*(one(item) for item in items)))


def _gb(value: int) -> str:
    return f"{value / GIB:.1f} GB"


async def admit_memory(db, extra: int, running: list[dict]) -> None:
    """The CLI reservations, plus running managed caps, plus this cap, must fit the host budget."""
    view = snapshot(db)
    used = sum(c["memory"] for c in running)
    if view["memory_reserved_bytes"] + used + extra > view["memory_budget_bytes"]:
        raise Denied(
            f"docker memory budget full: CLI reservations {_gb(view['memory_reserved_bytes'])} + running "
            f"managed containers {_gb(used)} + this container {_gb(extra)} exceed the host budget "
            f"{_gb(view['memory_budget_bytes'])}; stop something or lower the cap", 409)


async def admit_start(runtime, conv_id: str, info: dict, running: list[dict]) -> None:
    """Memory first, then (for GPU containers) the slot, the health check and free VRAM."""
    others = [c for c in running if c["id"] != info["Id"]]
    host = info.get("HostConfig") or {}
    await admit_memory(runtime.db, host.get("Memory") or 0, others)
    if not host.get("DeviceRequests"):
        return
    busy = [c for c in others if c["gpu_mb"] is not None]
    if len(busy) >= slots(runtime.db):
        raise Denied(f"GPU slot busy: {len(busy)} managed GPU container(s) running "
                     f"(limit {slots(runtime.db)}); wait for one to stop", 409)
    need = int(((info.get("Config") or {}).get("Labels") or {}).get(LABEL_GPU_MB) or 0)
    free = await gpu.free_mb(runtime, conv_id)
    if need > free:
        raise Denied(f"GPU has {free} MB free, this container declares it needs {need} MB", 409)
