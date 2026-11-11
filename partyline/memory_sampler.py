"""Read process memory and deliver advisory warnings."""

from __future__ import annotations

import asyncio
import sys

from .attachment_tmp import attachment_tmp_dir
from .hierarchy import ancestors
from .mention_relay import live_manager, post_private
from .resolved_notices import tag_memory_notice
from .cgroup_sample import cgroup_usage
from .process_memory import backstop_bytes, process_snapshot
from .memory_warning import tmpfs_note_for, warning_text  # noqa: F401  re-exported for the sampler's tests
from .top_processes import process_breakdown

_NO_PROCESS_TABLE = object()
_NO_CGROUP_SAMPLE = object()


def process_tree_rss(
    pid: int, platform: str | None = None,
    snapshot: tuple[dict[int, int], dict[int, int]] | None | object = _NO_PROCESS_TABLE,
) -> int | None:
    """Sum an observed process tree's RSS; fallback is advisory and racy."""
    listing = process_snapshot(platform) if snapshot is _NO_PROCESS_TABLE else snapshot
    if listing is None:
        return None
    parents, rss = listing
    members = {pid}
    while True:
        children = {child for child, parent in parents.items() if parent in members}
        if children.issubset(members):
            break
        members.update(children)
    return sum(rss[member] for member in members if member in rss) or None


def read_usage(adapter, *, process_table=_NO_PROCESS_TABLE,
               cgroup_sample=_NO_CGROUP_SAMPLE) -> tuple[int, int | None, str, int] | None:
    """Advisory usage (working set where cgroups exist), peak, source, and
    the raw ``memory.current`` so nothing hides behind the working set."""
    proc = getattr(adapter, "proc", None)
    pid = getattr(proc, "pid", None)
    if not isinstance(pid, int):
        return None
    if sys.platform.startswith("linux"):
        usage = cgroup_usage(pid) if cgroup_sample is _NO_CGROUP_SAMPLE else cgroup_sample
        if isinstance(usage, dict):
            return (usage["working_set"], usage["peak"], "cgroup", usage["current"])
        if usage is not None:
            return usage[0], usage[1], "cgroup", usage[0]
    if process_table is None:
        return None
    rss = process_tree_rss(pid, snapshot=process_table)
    return (rss, None, "rss", rss) if rss is not None else None


def crosses_warning(usage: int, cap: int, threshold: int) -> bool:
    required = (cap * threshold + 99) // 100
    return cap > 0 and usage >= required


def warning_limit(budget: int) -> int:
    """Warn before a Linux host clamp can kill below a saved budget."""
    return min(budget, backstop_bytes(budget)) if sys.platform.startswith("linux") else budget


async def _warn(runtime, row: dict, usage: int, cap: int, shmem: int = 0,
                sample: dict | None = None) -> None:
    """Tell the process itself, then the nearest captain above it, privately.

    Private copies still reach people on each line. A process near its cap is
    always told: a notice no process is rung for is one nobody acts on.
    ``shmem`` is the scope's shared-memory figure; the sentence naming it (finding
    5.15) is built here, once per warning actually sent, off the event loop.
    """
    tmp_note = await tmpfs_note_for(str(attachment_tmp_dir(row["id"])), shmem) or ""
    adapter = runtime.live.get(row["id"])
    pid = getattr(getattr(adapter, "proc", None), "pid", None)
    top = await asyncio.to_thread(process_breakdown, pid) if isinstance(pid, int) else []
    # The copy to the process itself must not name it as the speaker: routing
    # never rings a process with its own words.
    own = await post_private(runtime, row["conv_id"], "system", "system",
                             warning_text(row, usage, cap, own=True, top=top,
                                          tmp_note=tmp_note, sample=sample),
                             audience=row["id"], source=(None, row["conv_id"]))
    tag_memory_notice(runtime.db, own["id"], row["id"], cap)
    source = (row["id"], row["conv_id"])
    detail = warning_text(row, usage, cap, top=top, tmp_note=tmp_note, sample=sample)
    for line in [row["conv_id"], *ancestors(runtime.db, row["conv_id"])]:
        captain = live_manager(runtime, line)
        if captain is not None and captain["id"] != row["id"]:
            copy = await post_private(runtime, line, "system", "system", detail,
                                      audience=captain["id"], source=source)
            tag_memory_notice(runtime.db, copy["id"], row["id"], cap)
            return
