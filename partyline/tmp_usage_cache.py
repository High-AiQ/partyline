"""Stale-while-revalidate for bounded temp usage snapshots."""

import asyncio
import os
import threading
import time

_refresh_task: asyncio.Task | None = None
_refresh_lock = threading.Lock()
_EMPTY = {"tmp_total_bytes": None, "tmp_used_bytes": None,
          "sizes": {}, "tmp_partyline_bytes": 0}


def _refresh(cache, snapshot):
    with _refresh_lock:
        cache["value"] = snapshot()
        cache["at"] = time.monotonic()


def get(cache, snapshot, ttl, *, cached=True):
    global _refresh_task
    if cached and cache["value"] is not None and time.monotonic() - cache["at"] < ttl:
        return cache["value"]
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is None:
        if not _refresh_lock.acquire(blocking=False):
            return cache["value"] or _EMPTY
        try:
            cache["value"] = snapshot()
            cache["at"] = time.monotonic()
            return cache["value"]
        finally:
            _refresh_lock.release()
    if _refresh_task is None or _refresh_task.done():
        async def refresh():
            await asyncio.to_thread(_refresh, cache, snapshot)
        _refresh_task = loop.create_task(refresh())
    return cache["value"] or _EMPTY


def bounded_entries(root, deadline):
    names = []
    with os.scandir(root) as entries:
        for entry in entries:
            if time.monotonic() > deadline:
                break
            names.append(entry.name)
    return sorted(names)
