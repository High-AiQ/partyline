"""One bounded, advisory sampler for all live attachments."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import logging
import sys
import time

from .docker_workloads import inventory
from .hierarchy import ancestors
from .memory_contracts import MemoryUsageEvent
from .mention_relay import live_manager, post_private
from .resource_budget import cap_bytes, live_rows, settings
from .process_memory import (
    backstop_bytes, cgroup_usage, reclaim_scope)
from .resource_push import ResourcePusher
from .memory_warning import warning_text  # noqa: F401  re-exported for the sampler's tests
from .top_processes import top_descendants

INTERVAL = 5.0
CHUNK = 8
REARM_RATIO = 0.65
NOTICE_WINDOW = 600.0
logger = logging.getLogger(__name__)
_NO_PROCESS_TABLE = object()
_NO_CGROUP_SAMPLE = object()


def process_snapshot(platform: str | None = None) -> tuple[dict[int, int], dict[int, int]] | None:
    """Read a bounded process table once for a fallback batch.

    A process exiting between the listing and the read must not lose the
    whole table: entries that vanish mid-scan are skipped, not fatal. The
    sampler treats an empty table as no data; the signal endpoint's
    descendant check treats a partial table as partial truth, so a churning
    host degrades to an incomplete answer rather than a false refusal.
    """
    platform = sys.platform if platform is None else platform
    if platform.startswith("linux"):
        try:
            import os
            parents, rss = {}, {}
            for name in os.listdir("/proc"):
                if not name.isdigit():
                    continue
                try:
                    with open(f"/proc/{name}/stat", encoding="ascii") as stream:
                        fields = stream.read().rsplit(")", 1)[1].split()
                    child = int(name)
                    parents[child] = int(fields[1])
                    with open(f"/proc/{child}/status", encoding="ascii") as stream:
                        for line in stream:
                            if line.startswith("VmRSS:"):
                                rss[child] = int(line.split()[1]) * 1024
                                break
                except (OSError, ValueError, IndexError):
                    continue  # exited mid-scan; the table is partial, not void
            return parents, rss
        except (OSError, ValueError):
            return None
    try:
        import subprocess
        if platform.startswith("win"):
            command = ["powershell", "-NoProfile", "-Command",
                       "Get-CimInstance Win32_Process | ForEach-Object { "
                       "\"$($_.ProcessId),$($_.ParentProcessId),$($_.WorkingSetSize)\" }"]
        else:
            command = ["ps", "-axo", "pid=,ppid=,rss="]
        done = subprocess.run(command, capture_output=True, text=True, timeout=3, check=False)
        if done.returncode:
            return None
        parents, rss = {}, {}
        for line in done.stdout.splitlines():
            fields = line.strip().split(",") if platform.startswith("win") else line.split()
            if len(fields) == 3:
                child, parent, amount = map(int, fields)
                parents[child] = parent
                rss[child] = amount if platform.startswith("win") else amount * 1024
        return parents, rss
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


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


async def _warn(runtime, row: dict, usage: int, cap: int) -> None:
    """Tell the process itself, then the nearest captain above it, privately.

    Private copies still reach people on each line. A process near its cap is
    always told: a notice no process is rung for is one nobody acts on.
    """
    adapter = runtime.live.get(row["id"])
    pid = getattr(getattr(adapter, "proc", None), "pid", None)
    top = top_descendants(pid) if isinstance(pid, int) else []
    # The copy to the process itself must not name it as the speaker: routing
    # never rings a process with its own words.
    await post_private(runtime, row["conv_id"], "system", "system",
                       warning_text(row, usage, cap, own=True, top=top),
                       audience=row["id"], source=(None, row["conv_id"]))
    source = (row["id"], row["conv_id"])
    detail = warning_text(row, usage, cap, top=top)
    for line in [row["conv_id"], *ancestors(runtime.db, row["conv_id"])]:
        captain = live_manager(runtime, line)
        if captain is not None and captain["id"] != row["id"]:
            await post_private(runtime, line, "system", "system", detail,
                               audience=captain["id"], source=source)
            return



async def run(runtime, clock=time.monotonic, sampler=read_usage) -> None:
    """Sample in small slices, never creating a worker thread per process."""
    armed: dict[str, bool] = {}
    # Crossing the warning limit is told once per climb, outside the cooldown.
    over: dict[str, bool] = {}
    # Warning state belongs to one activation: a resumed process starts fresh.
    activation: dict[str, object] = {}
    notified: dict[str, float] = {}
    cursor = 0
    pusher = ResourcePusher(clock)
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="memory-sampler")
    loop = asyncio.get_running_loop()
    try:
        while True:
            try:
                rows = live_rows(runtime.db)
                live_ids = {row["id"] for row in rows}
                states = (runtime.memory_usage, armed, notified, over, activation)
                for attachment_id in set().union(*states) - live_ids:
                    for state in states:
                        state.pop(attachment_id, None)
                if rows:
                    start = cursor % len(rows)
                    batch = (rows[start:] + rows[:start])[:CHUNK]
                    cursor = (start + len(batch)) % len(rows)
                    cgroup_samples = {}
                    needs_snapshot = False
                    if sampler is read_usage:
                        for row in batch:
                            adapter = runtime.live.get(row["id"])
                            pid = getattr(getattr(adapter, "proc", None), "pid", None)
                            if not isinstance(pid, int):
                                continue
                            if sys.platform.startswith("linux"):
                                cgroup_samples[row["id"]] = cgroup_usage(pid)
                                needs_snapshot |= cgroup_samples[row["id"]] is None
                            else:
                                needs_snapshot = True
                    # A single off-loop process listing serves all RSS fallbacks.
                    table = (await loop.run_in_executor(executor, process_snapshot)
                             if needs_snapshot else None)
                    config = settings(runtime.db)
                    for row in batch:
                        adapter = runtime.live.get(row["id"])
                        if adapter is None:
                            continue
                        sample = (sampler(adapter, process_table=table,
                                          cgroup_sample=cgroup_samples.get(
                                              row["id"], _NO_CGROUP_SAMPLE))
                                  if sampler is read_usage else sampler(adapter))
                        if sample is None:
                            continue
                        if activation.get(row["id"]) is not adapter:
                            for state in (armed, notified, over):
                                state.pop(row["id"], None)
                            activation[row["id"]] = adapter
                        sample_dict = cgroup_samples.get(row["id"])
                        raw = sample[3] if len(sample) > 3 else sample[0]
                        usage = sample[0]
                        cap = cap_bytes(row, config)
                        effective = warning_limit(cap)
                        # The working-set fix (2.20 false alarms): file cache
                        # inflates memory.current past the threshold while the
                        # working set is fine. Ask the kernel to reclaim the
                        # difference and re-read before any "decide now"
                        # notice goes out. A failed reclaim simply leaves the
                        # working-set decision standing.
                        if (sample_dict is not None and usage < effective
                                and crosses_warning(raw, effective,
                                                    config["memory_warn_percent"])):
                            reclaim_scope(sample_dict["root"],
                                          sample_dict["current"] - usage)
                            pid = getattr(getattr(adapter, "proc", None),
                                          "pid", None)
                            fresh = (cgroup_usage(pid) if isinstance(pid, int)
                                     else None)
                            if fresh is not None:
                                usage = fresh["working_set"]
                                raw = fresh["current"]
                        if usage < effective * REARM_RATIO:
                            armed[row["id"]] = True
                            over[row["id"]] = False
                        elif usage >= effective > 0 and not over.get(row["id"]):
                            over[row["id"]] = True
                            armed[row["id"]] = False
                            notified[row["id"]] = clock()
                            await _warn(runtime, row, usage, cap)
                        elif crosses_warning(usage, effective, config["memory_warn_percent"]):
                            now = clock()
                            inside_window = now - notified.get(row["id"], -NOTICE_WINDOW) < NOTICE_WINDOW
                            if armed.get(row["id"], True) and not inside_window:
                                armed[row["id"]] = False
                                notified[row["id"]] = now
                                await _warn(runtime, row, usage, cap)
                        runtime.memory_usage[row["id"]] = {
                            "usage_bytes": usage, "cap_bytes": cap,
                            "raw_bytes": raw,
                            "percent": min(100, usage * 100 // max(cap, 1)),
                            "source": sample[2], "sampled_at": time.time(),
                        }
                        await runtime.broadcast(row["conv_id"], MemoryUsageEvent(
                            attachment_id=row["id"], usage_bytes=usage, cap_bytes=cap,
                            raw_bytes=raw,
                            percent=min(100, usage * 100 // max(cap, 1)),
                        ))
                await inventory.sample(runtime)
                await pusher.tick(runtime)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("memory sampler tick failed; continuing")
            await asyncio.sleep(INTERVAL)
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
