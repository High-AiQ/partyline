"""In-memory walkthrough lifecycle; no captured bytes are written here."""

import asyncio
from dataclasses import dataclass, field, replace
import os
import time

from .walkthrough import WalkthroughBuffer


def _limit(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, default)))
    except ValueError:
        return default


@dataclass
class Take:
    share_id: str
    conv_id: str
    owner_id: int
    device_id: str
    buffer: WalkthroughBuffer = field(default_factory=WalkthroughBuffer)
    started: float | None = None
    stopped: bool = False
    expiry: asyncio.TimerHandle | None = None
    deadline: asyncio.TimerHandle | None = None


class Takes:
    def __init__(self, hub):
        self.hub = hub
        self.clock = time.monotonic
        self.items: dict[str, Take] = {}
        self.duration = _limit("PARTYLINE_WALKTHROUGH_SECONDS", 600)
        self.frames = _limit("PARTYLINE_WALKTHROUGH_FRAMES", 600)
        self.bytes = _limit("PARTYLINE_WALKTHROUGH_BYTES", 128 * 1024 * 1024)
        self.total_bytes = _limit("PARTYLINE_WALKTHROUGH_TOTAL_BYTES", 512 * 1024 * 1024)

    def create(self, share):
        take = Take(share.share_id, share.conv_id, share.owner_id, share.device_id,
                    WalkthroughBuffer(self.duration * 1000, self.frames, self.bytes))
        self.items[share.share_id] = take
        # Even an abandoned permission prompt cannot retain a buffer forever.
        take.expiry = asyncio.get_running_loop().call_later(
            self.duration + 300, lambda: asyncio.create_task(self.expire(take)))
        return take

    def arm(self, take, share):
        if take.started is not None or take.stopped:
            raise ValueError("walkthrough is already started or stopped")
        take.started = self.clock()
        if share.frames:
            self.add(share, share.frames[-1])
        take.deadline = asyncio.get_running_loop().call_later(
            self.duration, lambda: asyncio.create_task(self.stop(take)))

    def add(self, share, frame):
        take = self.items.get(share.share_id)
        if take and take.started is not None and not take.stopped:
            elapsed = max(0, int((self.clock() - take.started) * 1000))
            other_bytes = sum(item.buffer.size for item in self.items.values() if item is not take)
            take.buffer.max_bytes = min(self.bytes, max(0, self.total_bytes - other_bytes))
            take.buffer.add(replace(frame, ts_ms=elapsed))

    async def stop(self, take):
        if not take.stopped:
            take.stopped = True
            if take.deadline:
                take.deadline.cancel()
            await self.hub.stop_share(take.share_id, "walkthrough stopped")

    def share_ended(self, share_id):
        take = self.items.get(share_id)
        if take:
            take.stopped = True
            if take.deadline:
                take.deadline.cancel()

    def discard(self, share_id):
        take = self.items.pop(share_id, None)
        if take:
            if take.expiry:
                take.expiry.cancel()
            if take.deadline:
                take.deadline.cancel()
            take.buffer.clear()

    async def expire(self, take):
        await self.stop(take)
        self.discard(take.share_id)
