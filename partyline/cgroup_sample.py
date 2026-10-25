"""Read and reclaim cgroup-v2 memory for one process scope (2.20, 5.15).

``read_cgroup_sample`` returns the raw ``memory.current``, the advisory
``working_set`` (current minus reclaimable file pages), anonymous and
file-cache figures from ``memory.stat``, the ``shmem`` figure (tmpfs pages,
finding 5.15) and the scope's ``root`` — so a caller can write
``memory.reclaim`` there and re-read.
"""

from __future__ import annotations


def read_cgroup_sample(root: str) -> dict | None:
    """Read ``memory.current``, ``memory.peak`` and ``memory.stat`` in a scope.

    With ``anon`` and ``file`` available, ``working_set`` is ``current`` minus
    file pages other than ``shmem``, clamped to at least ``anon``. Both active
    and inactive file cache can be dropped; tmpfs cannot. Older kernels missing
    either key fall back to ``current - inactive_file``. ``shmem`` is kept
    separately: deleting its files is the only way that memory goes down.
    """
    try:
        with open(f"{root}/memory.current", encoding="ascii") as stream:
            current = int(stream.read().strip())
    except (OSError, ValueError):
        return None
    try:
        with open(f"{root}/memory.peak", encoding="ascii") as stream:
            peak = int(stream.read().strip())
    except (OSError, ValueError):
        peak = None
    stat = dict.fromkeys(
        ("anon", "file", "inactive_file", "active_file", "kernel", "slab", "shmem"), 0,
    )
    seen = set()
    try:
        with open(f"{root}/memory.stat", encoding="ascii") as stream:
            for line in stream:
                key, value = line.split(maxsplit=1)
                if key in stat:
                    stat[key] = int(value)
                    seen.add(key)
            available = {"anon", "file"}.issubset(seen)
    except (OSError, ValueError):
        available = False
    inactive = stat["inactive_file"]
    working_set = max(0, current - inactive)
    kernel_total = None
    if available:
        working_set = max(stat["anon"], current - (stat["file"] - stat["shmem"]))
        kernel_total = max(0, current - stat["anon"] - stat["file"])
    else:
        stat.update(dict.fromkeys(("anon", "file", "active_file", "kernel", "slab")))
    return {"root": root, "current": current, "peak": peak, **stat,
            "kernel_total": kernel_total, "working_set": working_set}


def cgroup_usage(pid: int, base: str = "/sys/fs/cgroup") -> dict | None:
    """Locate one process's scope directory and sample it.

    ``root`` names the scope, so a caller can write ``memory.reclaim``
    there and re-read.
    """
    try:
        with open(f"/proc/{pid}/cgroup", encoding="ascii") as stream:
            relative = next(line.split("::", 1)[1].strip() for line in stream
                            if line.startswith("0::"))
        return read_cgroup_sample(f"{base}{relative}")
    except (OSError, StopIteration, ValueError):
        return None


def reclaim_scope(root: str, amount: int) -> bool:
    """Ask the kernel to reclaim ``amount`` bytes in the scope; best effort.

    A failed write is reported, never raised: the caller falls back to the
    working-set decision it already has.
    """
    if amount <= 0:
        return True
    try:
        with open(f"{root}/memory.reclaim", "w", encoding="ascii") as stream:
            stream.write(str(amount))
        return True
    except OSError:
        return False
