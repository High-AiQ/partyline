"""One bounded, advisory sampler for all live attachments."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import logging
import sys
import time

from .attachment_tmp import attachment_tmp_dir
from .docker_workloads import inventory
from .hierarchy import ancestors
from .legacy_tmp import reap_pytest_if_tmpfs
from .memory_contracts import MemoryUsageEvent
from .mention_relay import live_manager, post_private
from .resource_budget import cap_bytes, live_rows, settings
from .cgroup_sample import cgroup_usage, reclaim_scope
from .process_memory import backstop_bytes, process_snapshot
from .resource_push import ResourcePusher
from .memory_warning import tmpfs_note_for, warning_text  # noqa: F401  re-exported for the sampler's tests
from .top_processes import process_breakdown

INTERVAL = 5.0
CHUNK = 8
REARM_RATIO = 0.65
NOTICE_WINDOW = 600.0
RECLAIM_BACKOFF_SECONDS = 60.0
logger = logging.getLogger(__name__)
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


async def _warn(runtime, row: dict, usage: int, cap: int, shmem: int = 0) -> None:
    """Tell the process itself, then the nearest captain above it, privately.

    Private copies still reach people on each line. A process near its cap is
    always told: a notice no process is rung for is one nobody acts on.
    ``shmem`` is the scope's shared-memory figure; the sentence naming it (finding
    5.15) is built here, once per warning actually sent, off the event loop.
    """
    tmp_note = await tmpfs_note_for(str(attachment_tmp_dir(row["id"])), shmem) or ""
    adapter = runtime.live.get(row["id"])
    pid = getattr(getattr(adapter, "proc", None), "pid", None)
    top = process_breakdown(pid) if isinstance(pid, int) else []
    # The copy to the process itself must not name it as the speaker: routing
    # never rings a process with its own words.
    await post_private(runtime, row["conv_id"], "system", "system",
                       warning_text(row, usage, cap, own=True, top=top,
                                    tmp_note=tmp_note),
                       audience=row["id"], source=(None, row["conv_id"]))
    source = (row["id"], row["conv_id"])
    detail = warning_text(row, usage, cap, top=top, tmp_note=tmp_note)
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
    # One tmp-housekeeping pass per process per backoff window (finding 5.15).
    tmp_backoff: dict[str, float] = {}
    # One reclaim attempt per scope per backoff window (EAGAIN retry guard).
    reclaim_backoff: dict[str, float] = {}
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
                states = (runtime.memory_usage, armed, notified, over, activation,
                          reclaim_backoff, tmp_backoff)
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
                        # Finding 5.15: when the working set crosses the
                        # threshold, first reap old pytest runs in this
                        # process's own temp directory (once per backoff
                        # window), then re-read before deciding.
                        if (sample_dict is not None
                                and crosses_warning(usage, effective,
                                                    config["memory_warn_percent"])
                                and clock() - tmp_backoff.get(row["id"], -60.0)
                                >= 60.0):
                            tmp_backoff[row["id"]] = clock()
                            await asyncio.to_thread(reap_pytest_if_tmpfs,
                                                    attachment_tmp_dir(row["id"]))
                            pid = getattr(getattr(adapter, "proc", None),
                                          "pid", None)
                            fresh = (await asyncio.to_thread(cgroup_usage, pid)
                                     if isinstance(pid, int) else None)
                            if fresh is not None:
                                usage = fresh["working_set"]
                                raw = fresh["current"]
                                sample_dict = fresh
                        # The working-set fix: file cache inflates
                        # memory.current past the threshold while the working
                        # set is fine. Reclaim the difference off the event
                        # loop (with a per-attachment backoff — the kernel
                        # answers EAGAIN when it cannot reclaim the full
                        # amount), re-read, and only then decide.
                        attempted_recently = (
                            clock() - reclaim_backoff.get(row["id"], -RECLAIM_BACKOFF_SECONDS)
                            < RECLAIM_BACKOFF_SECONDS)
                        if (sample_dict is not None and usage < effective
                                and crosses_warning(raw, effective,
                                                    config["memory_warn_percent"])
                                and not attempted_recently):
                            reclaim_backoff[row["id"]] = clock()
                            amount = sample_dict["current"] - usage
                            await asyncio.to_thread(reclaim_scope,
                                                    sample_dict["root"], amount)
                            pid = getattr(getattr(adapter, "proc", None),
                                          "pid", None)
                            fresh = (await asyncio.to_thread(cgroup_usage, pid)
                                     if isinstance(pid, int) else None)
                            if fresh is not None:
                                usage = fresh["working_set"]
                                raw = fresh["current"]
                        shmem = (sample_dict or {}).get("shmem", 0)
                        if usage < effective * REARM_RATIO:
                            armed[row["id"]] = True
                            over[row["id"]] = False
                        elif usage >= effective > 0 and not over.get(row["id"]):
                            over[row["id"]] = True
                            armed[row["id"]] = False
                            notified[row["id"]] = clock()
                            await _warn(runtime, row, usage, cap, shmem=shmem)
                        elif crosses_warning(usage, effective, config["memory_warn_percent"]):
                            now = clock()
                            inside_window = now - notified.get(row["id"], -NOTICE_WINDOW) < NOTICE_WINDOW
                            if armed.get(row["id"], True) and not inside_window:
                                armed[row["id"]] = False
                                notified[row["id"]] = now
                                await _warn(runtime, row, usage, cap, shmem=shmem)
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
                inventory.kick(runtime)
                await pusher.tick(runtime)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("memory sampler tick failed; continuing")
            await asyncio.sleep(INTERVAL)
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
