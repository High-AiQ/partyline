"""Push the fleet resource snapshot to open tabs when it moves.

Replaces the per-tab 5 s poll of ``GET /api/resources``: the memory sampler
already ticks on that cadence, so the snapshot is computed once per tick and
shared. With no websocket open nothing is computed. A quiet fleet still sends
one heartbeat every ``HEARTBEAT`` seconds so a tab can tell the push is alive.
"""

from __future__ import annotations

import asyncio
import time

from .contracts import ResourceSnapshotEvent
from .resource_budget import memory_ceiling, snapshot

HEARTBEAT = 60.0
MOVE_BYTES = 64 * 1024**2
MOVE_FRACTION = 0.005
USED = ("host_used_bytes", "partyline_used_bytes", "tmp_used_bytes")
EXACT = ("live_processes", "max_live_processes", "memory_reserve_bytes")


def moved(previous: dict, current: dict) -> bool:
    """Whether the numbers a tab shows changed enough to be worth a frame."""
    if any(previous.get(key) != current.get(key) for key in EXACT):
        return True
    threshold = min(MOVE_BYTES, MOVE_FRACTION * (current.get("host_ram_bytes") or MOVE_BYTES * 200))
    for key in USED:
        before, after = previous.get(key), current.get(key)
        if (before is None) != (after is None):
            return True
        if after is not None and abs(after - before) >= threshold:
            return True
    return False


def _view(runtime) -> dict:
    """The same body ``GET /api/resources`` returns."""
    return {**snapshot(runtime.db, None, runtime), "memory_ceiling_bytes": memory_ceiling()}


class ResourcePusher:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._sent: dict | None = None
        self._sent_at = 0.0

    async def tick(self, runtime) -> bool:
        """Broadcast the snapshot if it moved or the heartbeat is due; report whether it did."""
        if not any(getattr(runtime, "sockets", {}).values()):
            return False
        view = await asyncio.to_thread(_view, runtime)
        now = self._clock()
        if self._sent is not None and not moved(self._sent, view) and now - self._sent_at < HEARTBEAT:
            return False
        self._sent, self._sent_at = view, now
        await runtime.broadcast_all(ResourceSnapshotEvent(snapshot=view))
        return True
