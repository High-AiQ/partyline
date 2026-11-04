"""Apply an approved memory raise to a running process without restarting it."""

from __future__ import annotations

import asyncio
import subprocess
import sys

from fastapi import HTTPException

from .process_counts import counts
from .process_exit import SCOPE
from .process_memory import backstop_bytes, parse_size
from .resource_budget import memory_ceiling, reject_if_full, settings

CAPTAIN_HINT = ("this memory limit exceeds the captain approval ceiling; file a memory request "
                "for a person to decide")


def check_task_memory(db, actor, requested: str | None) -> None:
    """Same ceilings as a memory request: the host's, plus the captain's for a machine."""
    if requested is None:
        return
    amount = parse_size(requested)
    ceiling = memory_ceiling()
    if amount > ceiling:
        raise HTTPException(400, f"requested limit exceeds the host ceiling of {ceiling} bytes")
    if actor.kind == "machine" and amount > settings(db)["memory_captain_ceiling_bytes"]:
        raise HTTPException(403, CAPTAIN_HINT)


def _systemctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True,
                          timeout=10, check=False)


def read_scope_memory_max(unit: str) -> str | None:
    """The kernel's memory.max for a scope, read from its cgroup directory."""
    done = _systemctl("show", unit, "--property=ControlGroup", "--value")
    group = done.stdout.strip()
    if done.returncode or not group.startswith("/"):
        return None
    try:
        with open(f"/sys/fs/cgroup{group}/memory.max", encoding="ascii") as stream:
            return stream.read().strip()
    except OSError:
        return None


def _raise_sync(unit: str, limit: str) -> bool:
    wanted = backstop_bytes(parse_size(limit))
    done = _systemctl("set-property", "--runtime", unit,
                      f"MemoryMax={wanted}", "MemorySwapMax=0")
    if done.returncode:
        return False
    return read_scope_memory_max(unit) == str(wanted)


async def raise_live(runtime, att_id: str, limit: str) -> bool:
    """Raise the running scope's backstop; True only when memory.max reads back as set."""
    adapter = runtime.live.get(att_id)
    unit = getattr(adapter, "memory_scope", None)
    if (not sys.platform.startswith("linux") or not isinstance(unit, str)
            or not SCOPE.fullmatch(unit)):
        return False
    # Admission first: a full budget refuses (409) rather than restart, which would be refused too.
    async with runtime.db._runtime_serialized_async():
        att = runtime.db.get_attachment(att_id)
        if att and counts(att):
            reject_if_full(runtime.db, parse_size(limit), exclude_id=att_id)
        try:
            ok = await asyncio.to_thread(_raise_sync, unit, limit)
        except (OSError, subprocess.SubprocessError):
            return False
    if not ok:
        return False
    adapter.memory_limit = limit
    if isinstance(getattr(adapter, "att", None), dict):
        adapter.att["memory_limit"] = limit
    return True
