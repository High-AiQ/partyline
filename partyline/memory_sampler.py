"""One bounded, advisory sampler for all live attachments."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import logging
import sys
import time

from .hierarchy import ancestors
from .memory_contracts import MemoryUsageEvent
from .mention_relay import live_manager, post_private
from .resource_budget import cap_bytes, live_rows, memory_ceiling, settings
from .process_memory import format_memory_bytes, suggested_memory_limit

INTERVAL = 5.0
CHUNK = 8
REARM_RATIO = 0.65
NOTICE_WINDOW = 600.0
logger = logging.getLogger(__name__)
_NO_PROCESS_TABLE = object()
_NO_CGROUP_SAMPLE = object()


def suggested_limit(cap: int) -> str | None:
    return suggested_memory_limit(cap, memory_ceiling())


def cgroup_usage(pid: int) -> tuple[int, int | None] | None:
    """Read the process scope's current and peak cgroup-v2 memory in bytes."""
    try:
        with open(f"/proc/{pid}/cgroup", encoding="ascii") as stream:
            relative = next(line.split("::", 1)[1].strip() for line in stream
                            if line.startswith("0::"))
        root = f"/sys/fs/cgroup{relative}"
        with open(f"{root}/memory.current", encoding="ascii") as stream:
            current = int(stream.read().strip())
        try:
            with open(f"{root}/memory.peak", encoding="ascii") as stream:
                peak = int(stream.read().strip())
        except (OSError, ValueError):
            peak = None
        return current, peak
    except (OSError, StopIteration, ValueError):
        return None


def process_snapshot(platform: str | None = None) -> tuple[dict[int, int], dict[int, int]] | None:
    """Read a bounded process table once for a fallback batch."""
    platform = sys.platform if platform is None else platform
    if platform.startswith("linux"):
        try:
            parents, rss = {}, {}
            import os
            for name in os.listdir("/proc"):
                if not name.isdigit():
                    continue
                with open(f"/proc/{name}/stat", encoding="ascii") as stream:
                    fields = stream.read().rsplit(")", 1)[1].split()
                child = int(name)
                parents[child] = int(fields[1])
                with open(f"/proc/{child}/status", encoding="ascii") as stream:
                    for line in stream:
                        if line.startswith("VmRSS:"):
                            rss[child] = int(line.split()[1]) * 1024
                            break
            return parents, rss
        except (OSError, ValueError, IndexError):
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
               cgroup_sample=_NO_CGROUP_SAMPLE) -> tuple[int, int | None, str] | None:
    proc = getattr(adapter, "proc", None)
    pid = getattr(proc, "pid", None)
    if not isinstance(pid, int):
        return None
    if sys.platform.startswith("linux"):
        usage = cgroup_usage(pid) if cgroup_sample is _NO_CGROUP_SAMPLE else cgroup_sample
        if usage is not None:
            return usage[0], usage[1], "cgroup"
    if process_table is None:
        return None
    rss = process_tree_rss(pid, snapshot=process_table)
    return (rss, None, "rss") if rss is not None else None


def crosses_warning(usage: int, cap: int, threshold: int) -> bool:
    required = (cap * threshold + 99) // 100
    return cap > 0 and usage >= required


async def _warn(runtime, row: dict, usage: int, cap: int) -> None:
    """Tell the process itself, then the nearest captain above it, privately.

    Private copies still reach people on each line. A process near its cap is
    always told: a notice no process is rung for is one nobody acts on.
    """
    # The copy to the process itself must not name it as the speaker: routing
    # never rings a process with its own words.
    await post_private(runtime, row["conv_id"], "system", "system",
                       warning_text(row, usage, cap, own=True),
                       audience=row["id"], source=(None, row["conv_id"]))
    source = (row["id"], row["conv_id"])
    detail = warning_text(row, usage, cap)
    for line in [row["conv_id"], *ancestors(runtime.db, row["conv_id"])]:
        captain = live_manager(runtime, line)
        if captain is not None and captain["id"] != row["id"]:
            await post_private(runtime, line, "system", "system", detail,
                               audience=captain["id"], source=source)
            return


def cap_enforcement(platform: str) -> str:
    """Say honestly what reaching the cap does on this host."""
    if platform.startswith("linux"):
        return ("Past the cap the kernel may kill this process if it cannot reclaim "
                "enough memory.")
    if platform.startswith("win"):
        return "The cap is a hard limit: allocations past it fail and the process may exit."
    # macOS gets only a best-effort address-space limit, not a resident one.
    return ("This host cannot enforce the cap on resident memory, so growth past it "
            "eats into memory every other process needs.")


def warning_text(row: dict, usage: int, cap: int, *, own: bool = False) -> str:
    """Build the warning; ``own`` words it for the process that is near its cap."""
    percent = usage * 100 // max(cap, 1)
    request_limit = suggested_limit(cap)
    request_hint = (
        f'POST /api/attachments/{row["id"]}/memory-requests with '
        f'{{"requested_limit":"{request_limit}","reason":"…"}}; '
        "approval restarts the process with the new cap."
        if request_limit else "The host ceiling prevents a larger cap."
    )
    used = (f"{format_memory_bytes(usage)} of its {format_memory_bytes(cap)} "
            f"per-process memory cap ({percent}%)")
    if own:
        fate = cap_enforcement(sys.platform)
        return (f"⚠ {row['name']}, you are using {used}. {fate} Commit or save your work "
                "now, then find and stop what is growing (a build, test run, or cache). If "
                "the work genuinely needs more, file a request with a reason for a person to "
                f"approve: {request_hint}")
    return (f"⚠ {row['name']} is using {used}. It has been told to save its work. As its "
            "captain, decide now: have it cut what is growing, or file a justified higher cap "
            f"for a person to approve, and tell the person which you chose. {request_hint}")


async def run(runtime, clock=time.monotonic, sampler=read_usage) -> None:
    """Sample in small slices, never creating a worker thread per process."""
    armed: dict[str, bool] = {}
    notified: dict[str, float] = {}
    cursor = 0
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="memory-sampler")
    loop = asyncio.get_running_loop()
    try:
        while True:
            try:
                rows = live_rows(runtime.db)
                live_ids = {row["id"] for row in rows}
                for attachment_id in set(runtime.memory_usage) - live_ids:
                    runtime.memory_usage.pop(attachment_id, None)
                    armed.pop(attachment_id, None)
                    notified.pop(attachment_id, None)
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
                        usage = sample[0]
                        cap = cap_bytes(row, config)
                        if usage < cap * REARM_RATIO:
                            armed[row["id"]] = True
                        elif crosses_warning(usage, cap, config["memory_warn_percent"]):
                            now = clock()
                            inside_window = now - notified.get(row["id"], -NOTICE_WINDOW) < NOTICE_WINDOW
                            if armed.get(row["id"], True) and not inside_window:
                                armed[row["id"]] = False
                                notified[row["id"]] = now
                                await _warn(runtime, row, usage, cap)
                        runtime.memory_usage[row["id"]] = {
                            "usage_bytes": usage, "cap_bytes": cap,
                            "percent": min(100, usage * 100 // max(cap, 1)),
                            "source": sample[2], "sampled_at": time.time(),
                        }
                        await runtime.broadcast(row["conv_id"], MemoryUsageEvent(
                            attachment_id=row["id"], usage_bytes=usage, cap_bytes=cap,
                            percent=min(100, usage * 100 // max(cap, 1)),
                        ))
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("memory sampler tick failed; continuing")
            await asyncio.sleep(INTERVAL)
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
