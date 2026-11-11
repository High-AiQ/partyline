"""Read current per-process gauges when a caller asks for a snapshot."""

import asyncio
import sys
import time

from .cgroup_sample import cgroup_usage
from .memory_sampler import process_snapshot, read_usage
from .resource_budget import cap_bytes, live_rows, settings


def _read(db, live):
    if not live:
        return {}
    rows = live_rows(db)
    config = settings(db)
    samples = {}
    readings = {}
    needs_table = False
    for row in rows:
        adapter = live.get(row["id"])
        pid = getattr(getattr(adapter, "proc", None), "pid", None)
        if not isinstance(pid, int):
            readings[row["id"]] = None
            continue
        sample = cgroup_usage(pid) if sys.platform.startswith("linux") else None
        samples[row["id"]] = sample
        needs_table |= sample is None
    table = process_snapshot() if needs_table else None
    for row in rows:
        ident = row["id"]
        if ident not in samples:
            continue
        cgroup = samples[ident]
        reading = read_usage(live[ident], process_table=table, cgroup_sample=cgroup)
        if reading is None:
            readings[ident] = None
            continue
        usage, _, source, raw = reading
        cap = cap_bytes(row, config)
        readings[ident] = {
            "usage_bytes": usage, "cap_bytes": cap, "raw_bytes": raw,
            "anon_bytes": (cgroup or {}).get("anon"), "file_bytes": (cgroup or {}).get("file"),
            "kernel_bytes": (cgroup or {}).get("kernel_total"),
            "percent": min(100, usage * 100 // max(cap, 1)), "source": source, "sampled_at": time.time(),
        }
    return readings


async def refresh(runtime):
    """Refresh gauges once off-loop; publish only for the same activation."""
    live = dict(getattr(runtime, "live", {}))
    readings = await asyncio.to_thread(_read, runtime.db, live)
    for ident, reading in readings.items():
        if getattr(runtime, "live", {}).get(ident) is not live.get(ident):
            continue
        if reading is None:
            runtime.memory_usage.pop(ident, None)
        else:
            runtime.memory_usage[ident] = reading
