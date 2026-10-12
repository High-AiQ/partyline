"""Real memory usage behind the resource snapshot: host numbers and the
partyline split. Sampling stays injectable — nothing here is read without a
caller passing paths, so tests never touch the real ``/proc``."""

from __future__ import annotations

import sys
import time
from pathlib import Path

GIB = 1024**3
TOP_LINES = 3


def host_available_bytes(meminfo_path: str = "/proc/meminfo") -> int | None:
    """Memory the host could still hand out, or None where the OS reports none."""
    if sys.platform == "win32":
        from .windows_server import memory_status
        try:
            return memory_status()[1]
        except OSError:
            return None
    try:
        for line in Path(meminfo_path).read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    except (OSError, IndexError, ValueError):
        return None
    return None


def server_usage_bytes(cgroup_root: str = "/sys/fs/cgroup",
                       self_cgroup: str = "/proc/self/cgroup",
                       self_status: str = "/proc/self/status") -> int | None:
    """This server's cgroup ``memory.current``, falling back to its RSS."""
    try:
        relative = next(line.split(":", 2)[2] for line in
                        Path(self_cgroup).read_text().splitlines()
                        if line.startswith("0::"))
        current = (Path(cgroup_root) / relative.lstrip("/")
                   / "memory.current").read_text().strip()
        if current.isdigit():
            return int(current)
    except (OSError, StopIteration):
        pass
    try:
        for line in Path(self_status).read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except (OSError, IndexError, ValueError):
        return None
    return None


def usage_bytes_for(runtime, attachment_id: str) -> int:
    if runtime is None:
        return 0
    return (runtime.memory_usage.get(attachment_id, {}).get("usage_bytes", 0) or 0)


def usage_section(runtime, rows: list[dict], host, roots: dict) -> dict:
    """Real numbers for the snapshot: host used/available, the partyline split,
    and the lines whose families actually use the most memory."""
    available = host.available_bytes
    used = host.ram_bytes - available if available is not None else None
    server = server_usage_bytes()
    processes = sum(usage_bytes_for(runtime, row["id"]) for row in rows)
    partyline = server + processes if server is not None else None
    other = (max(0, used - partyline)
             if used is not None and partyline is not None else None)
    totals: dict[str, list] = {}
    for row in rows:
        root_id, name = roots.get(row["conv_id"], (row["conv_id"], row["line_name"]))
        totals.setdefault(root_id, [name, 0])[1] += usage_bytes_for(runtime, row["id"])
    top = sorted(totals.items(), key=lambda item: -item[1][1])[:TOP_LINES]
    return {
        "host_used_bytes": used,
        "host_available_bytes": available,
        "partyline_server_bytes": server,
        "partyline_processes_bytes": processes,
        "partyline_used_bytes": partyline,
        "other_used_bytes": other,
        "sampled_at": time.time(),
        "top_lines": [
            {"line_id": line_id, "line": name, "usage_bytes": total}
            for line_id, (name, total) in top
        ],
    }


def gib_text(amount: int) -> str:
    """Human gigabytes for refusal messages: one decimal, whole when even."""
    value = amount / GIB
    rounded = round(value, 1)
    return f"{rounded:.1f} GB" if rounded % 1 else f"{int(rounded)} GB"
