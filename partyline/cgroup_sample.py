"""Read and reclaim cgroup-v2 memory for one process scope (2.20, 5.15).

``read_cgroup_sample`` returns the raw ``memory.current``, the advisory
``working_set`` (current minus ``inactive_file``), the ``shmem`` figure
(tmpfs pages, finding 5.15) and the scope's ``root`` — so a caller can
write ``memory.reclaim`` there and re-read.
"""

from __future__ import annotations


def read_cgroup_sample(root: str) -> dict | None:
    """Read ``memory.current``, ``memory.peak`` and ``memory.stat`` in a scope.

    ``working_set`` is ``current`` minus ``inactive_file``, floored at 0 —
    the figure kubelet and cAdvisor use, so file cache the kernel can
    reclaim never reads as real pressure. ``shmem`` (tmpfs pages) is kept
    separately: the kernel cannot reclaim it, and deleting the files is the
    only way it goes down.
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
    inactive, shmem = 0, 0
    try:
        with open(f"{root}/memory.stat", encoding="ascii") as stream:
            for line in stream:
                if line.startswith("inactive_file "):
                    inactive = int(line.split()[1])
                elif line.startswith("shmem "):
                    shmem = int(line.split()[1])
                if inactive and shmem:
                    break
    except (OSError, ValueError):
        pass
    return {"root": root, "current": current, "peak": peak, "shmem": shmem,
            "working_set": max(0, current - inactive)}


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
