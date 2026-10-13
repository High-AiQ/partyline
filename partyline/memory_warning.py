"""The memory warning's words: what the cap does, and who is eating it.

Split from `memory_sampler` when the warning grew a name list (5.10): the
sampler stays the state machine, this module is only the prose it sends.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from .process_memory import backstop_bytes, format_memory_bytes, suggested_memory_limit
from .resource_budget import memory_ceiling

SHMEM_NOTICE_BYTES = 256 * 1024**2


def suggested_limit(cap: int) -> str | None:
    return suggested_memory_limit(cap, memory_ceiling())


def format_top(top: list[dict]) -> str:
    """The largest descendants, one clause; an empty list renders nothing."""
    if not top:
        return ""
    named = "; ".join(
        f"pid {entry['pid']} ({format_memory_bytes(entry['rss'])}) {entry['cmdline']}"
        for entry in top)
    return (f" Its largest processes: {named}. Stop these by pid "
            "(kill <pid>, or POST /api/attachments/<id>/signal); never `pkill -f`/`killall`.")


def cap_enforcement(platform: str, cap: int) -> str:
    """Say honestly what reaching the cap does on this host."""
    if platform.startswith("linux"):
        hard = backstop_bytes(cap)
        backstop = format_memory_bytes(hard)
        if hard <= cap:
            return (f"On this host the {backstop} emergency backstop is at or below the "
                    f"{format_memory_bytes(cap)} budget. Warnings use the backstop; the kernel "
                    "may kill this process there if it cannot reclaim enough memory.")
        return ("The budget is advisory, so nothing stops you there, but at the "
                f"{backstop} emergency backstop the kernel kills this process.")
    if platform.startswith("win"):
        return "On this host the budget is a hard limit: allocations past it fail and the process may exit."
    # macOS gets only a best-effort address-space limit, not a resident one.
    return ("This host cannot enforce the budget on resident memory, so growth past it "
            "eats into memory every other process needs.")


def tmpfs_note(shmem: int, tmp_dir: str,
               largest: tuple[str, int] | None) -> str | None:
    """The tmpfs-share sentence (finding 5.15), or None under the threshold.

    ``shmem`` is the scope's ``memory.stat`` shmem figure; ``largest`` is
    the biggest directory under the process's own temp directory, as
    ``largest_dir_under`` reported it.
    """
    if shmem <= SHMEM_NOTICE_BYTES:
        return None
    under = ""
    if largest:
        under = (f" (largest under {tmp_dir}: {largest[0]} "
                 f"{largest[1] / 1024**3:.1f} GiB)")
    return (f"{shmem / 1024**3:.1f} GiB of this is files on tmpfs{under}. "
            "Deleting them frees the memory; reclaim cannot.")


async def tmpfs_note_for(tmp_dir: str, shmem: int) -> str | None:
    """``tmpfs_note`` with the bounded directory walk run off the loop."""
    if shmem <= SHMEM_NOTICE_BYTES:
        return None
    from .temp_mounts import largest_dir_under

    largest = await asyncio.to_thread(largest_dir_under, Path(tmp_dir))
    return tmpfs_note(shmem, tmp_dir, largest)


def warning_text(row: dict, usage: int, cap: int, *, own: bool = False,
                 top: list[dict] | None = None, tmp_note: str = "") -> str:
    """Build the warning; ``own`` words it for the process that is near its cap.

    ``top`` names the largest descendants (see ``top_processes``); both
    variants get the names, because both readers need to know what to stop.
    ``tmp_note`` carries the tmpfs-share sentence (finding 5.15) when the
    process holds a meaningful share of its temp filesystem in memory.
    """
    percent = usage * 100 // max(cap, 1)
    request_limit = suggested_limit(cap)
    request_hint = (
        f'POST /api/attachments/{row["id"]}/memory-requests with '
        f'{{"requested_limit":"{request_limit}","reason":"…"}}; '
        "approval restarts the process with the new budget."
        if request_limit else "The host ceiling prevents a larger budget."
    )
    guilty = format_top(top or [])
    tmp = f" {tmp_note}" if tmp_note else ""
    used = (f"{format_memory_bytes(usage)} of {'your' if own else 'its'} {format_memory_bytes(cap)} "
            f"per-process memory budget ({percent}%)")
    if own:
        fate = cap_enforcement(sys.platform, cap)
        return (f"⚠ {row['name']}, you are using {used}.{guilty}{tmp} {fate} Commit or save your work "
                "now, then find and stop what is growing (a build, test run, or cache). If "
                "the work genuinely needs more, file a request with a reason for a person to "
                f"approve: {request_hint}")
    clamp = (cap_enforcement(sys.platform, cap) + " "
             if sys.platform.startswith("linux") and backstop_bytes(cap) <= cap else "")
    return (f"⚠ {row['name']} is using {used}.{guilty}{tmp} {clamp}It has been told to save its work. "
            "As its captain, decide now: have it cut what is growing, or file a justified higher "
            f"budget for a person to approve, and tell the person which you chose. {request_hint}")
