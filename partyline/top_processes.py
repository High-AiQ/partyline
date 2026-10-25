"""The biggest resident descendants of a process, aggregated by command, for a human.

The memory sampler has always known a tree's total RSS and never which
process inside it is responsible. When a line goes near its cap the useful
sentence names what is growing, grouped by command: a browser's twenty
renderer and GPU children are one answer, not twenty, and they are most of the
memory in a Playwright run. Each group carries its count, its summed RSS, and
the pid of its largest member, which is what a person stops. The pid is shown
**as the process inside the fence sees it**: the last field of ``NSpid`` in
``/proc/<pid>/status``, which is the same number the fenced process would use
in its own ``pkill``/``kill``. The sampler runs outside the fence, on host
pids, so the translation is this module's job.

Reading is bounded: one pass over the process table, one ``/proc`` cmdline
read per descendant (512 bytes at most), and one ``NSpid`` read per group.
Called from the warning path only — once per climb, not per sample.
"""

from __future__ import annotations

import os
import sys

CMDLINE_CHARS = 60
GROUP_LIMIT = 5


def namespace_pid(host_pid: int) -> int:
    """The pid as the process itself sees it: the last NSpid field.

    A process in the root namespace has one NSpid field and answers its own
    host pid, so the common case costs one read and no arithmetic. A nested
    namespace (a fenced process, then a bwrap inside it) lists every level;
    the last is the innermost view, which is what its shell reports.
    """
    try:
        with open(f"/proc/{host_pid}/status", encoding="ascii") as stream:
            for line in stream:
                if line.startswith("NSpid:"):
                    return int(line.split()[-1])
    except (OSError, ValueError, IndexError):
        pass
    return host_pid


def argv(host_pid: int) -> list[str]:
    """The first 512 bytes of a process's argument vector, decoded; empty when unreadable."""
    try:
        with open(f"/proc/{host_pid}/cmdline", "rb") as stream:
            raw = stream.read(512)
    except OSError:
        return []
    return [part.decode("utf-8", "replace") for part in raw.split(b"\0") if part]


def render(parts: list[str]) -> str:
    """A bounded, printable command line; an empty argument vector reads as '?'."""
    if not parts:
        return "?"
    text = " ".join(parts)
    return text if len(text) <= CMDLINE_CHARS else text[: CMDLINE_CHARS - 1] + "…"


def _descendants(parents: dict[int, int], pid: int) -> set[int]:
    members = {pid}
    while True:
        children = {child for child, parent in parents.items() if parent in members}
        if children.issubset(members):
            return members
        members.update(children)


def process_breakdown(host_pid: int, limit: int = GROUP_LIMIT,
                      snapshot: tuple[dict[int, int], dict[int, int]] | None = None,
                      ) -> list[dict]:
    """The ``limit`` largest command groups under ``host_pid``, biggest first.

    The root itself is excluded: the agent (or its CLI) is the process being
    warned, not one of the culprits. Members are grouped by the basename of
    their argv[0], so every Chromium renderer, GPU and zygote process is one
    ``chrome`` group. Each entry is ``{"command", "count", "rss", "pid",
    "cmdline"}``: the group's summed RSS, and the largest member's pid in its
    own namespace and command line. Empty when the platform cannot say.
    """
    if not sys.platform.startswith("linux"):
        return []
    if snapshot is None:
        from .memory_sampler import process_snapshot

        snapshot = process_snapshot("linux")
    if snapshot is None:
        return []
    parents, rss = snapshot
    groups: dict[str, dict] = {}
    for member in _descendants(parents, host_pid) - {host_pid}:
        if member not in rss:
            continue
        parts = argv(member)
        command = os.path.basename(parts[0]) if parts else "?"
        group = groups.setdefault(command, {"command": command, "count": 0, "rss": 0,
                                            "largest": -1, "pid": member, "cmdline": "?"})
        group["count"] += 1
        group["rss"] += rss[member]
        if rss[member] > group["largest"]:
            group.update(largest=rss[member], pid=member, cmdline=render(parts))
    ranked = sorted(groups.values(), key=lambda group: group["rss"], reverse=True)[:limit]
    for group in ranked:
        group["pid"] = namespace_pid(group["pid"])
        del group["largest"]
    return ranked
