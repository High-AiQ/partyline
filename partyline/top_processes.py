"""The biggest resident descendants of a process, named for a human.

The memory sampler has always known a tree's total RSS and never which
process inside it is responsible. When a line goes near its cap the useful
sentence names the three largest descendants — pid, RSS, a short command —
because "stop what is growing" is advice a person cannot follow without a
name. The pid is shown **as the process inside the fence sees it**: the last
field of ``NSpid`` in ``/proc/<pid>/status``, which is the same number the
fenced process would use in its own ``pkill``/``kill``. The sampler runs
outside the fence, on host pids, so the translation is this module's job.

Reading is bounded: one pass over the process table, three ``/proc`` reads
per named process. Called from the warning path only — once per climb, not
per sample.
"""

from __future__ import annotations

import sys

CMDLINE_CHARS = 60


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


def short_cmdline(host_pid: int) -> str:
    """A bounded, printable command line; the empty pid string reads as '?'."""
    try:
        with open(f"/proc/{host_pid}/cmdline", "rb") as stream:
            raw = stream.read(512)
    except OSError:
        return "?"
    parts = [part.decode("utf-8", "replace") for part in raw.split(b"\0") if part]
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


def top_descendants(host_pid: int, limit: int = 3,
                    snapshot: tuple[dict[int, int], dict[int, int]] | None = None,
                    ) -> list[dict]:
    """The ``limit`` largest-RSS strict descendants of ``host_pid``.

    The root itself is excluded: the agent (or its CLI) is the process being
    warned, not one of the culprits. Returns entries of
    ``{"pid", "rss", "cmdline"}`` with the pid in the process's own
    namespace, biggest first; empty when the platform cannot say.
    """
    if not sys.platform.startswith("linux"):
        return []
    if snapshot is None:
        from .memory_sampler import process_snapshot

        snapshot = process_snapshot("linux")
    if snapshot is None:
        return []
    parents, rss = snapshot
    members = _descendants(parents, host_pid) - {host_pid}
    ranked = sorted((m for m in members if m in rss),
                    key=lambda m: rss[m], reverse=True)[:limit]
    return [{"pid": namespace_pid(member), "rss": rss[member],
             "cmdline": short_cmdline(member)} for member in ranked]
