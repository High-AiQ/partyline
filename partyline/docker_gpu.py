"""GPU admission for managed containers: health first, then one heavy job at a time.

A failing ``nvidia-smi`` (or none at all) marks the GPU unhealthy. From then on
every GPU start is refused and the line and its root line are told once. Only a
person clears the mark (``POST /api/docker-gpu/clear``); nothing here ever tries
to reset the GPU.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import time

from .docker_policy import Denied
from .hierarchy import ancestors
from .system_notice import post_system_notice

logger = logging.getLogger(__name__)
SMI = "nvidia-smi"
TIMEOUT = 10.0
TTL = 5.0
SETTING = "docker_gpu_slots"


def slots(db) -> int:
    try:
        return max(1, int(db.get_setting(SETTING) or 1))
    except ValueError:
        return 1


async def probe() -> int:
    """Free VRAM in MB on the emptiest GPU; ``OSError`` says why it could not be read."""
    smi = shutil.which(SMI)
    if smi is None:
        raise OSError("nvidia-smi is not installed")
    proc = await asyncio.create_subprocess_exec(
        smi, "--query-gpu=memory.free", "--format=csv,noheader,nounits",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), TIMEOUT)
    except TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise OSError(f"nvidia-smi timed out after {int(TIMEOUT)} s") from exc
    if proc.returncode != 0:
        raise OSError(f"nvidia-smi exited {proc.returncode}: {err.decode(errors='replace')[:200].strip()}")
    try:
        return max(int(value) for value in out.decode().split())
    except ValueError as exc:
        raise OSError(f"nvidia-smi output unreadable: {out[:80]!r}") from exc


class Gpu:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self.unhealthy: str | None = None
        self._at = float("-inf")
        self._free = 0

    async def free_mb(self, runtime, conv_id: str) -> int:
        if self.unhealthy:
            raise Denied(f"the GPU is marked unhealthy ({self.unhealthy}); GPU starts are refused until "
                         "a person clears it (POST /api/docker-gpu/clear)", 503)
        if self._clock() - self._at >= TTL:
            try:
                self._free = await probe()
            except OSError as exc:
                await self.mark(runtime, conv_id, str(exc))
                raise Denied(f"the GPU health check failed ({exc}); GPU starts are refused until a "
                             "person clears it (POST /api/docker-gpu/clear)", 503) from exc
            self._at = self._clock()
        return self._free

    async def mark(self, runtime, conv_id: str, reason: str) -> None:
        first = self.unhealthy is None
        self.unhealthy = reason
        logger.warning("docker gpu marked unhealthy: %s", reason)
        if not first:
            return
        root = [*ancestors(runtime.db, conv_id)][-1:] or [conv_id]
        for line in dict.fromkeys([conv_id, *root]):
            await post_system_notice(
                runtime, line, f"⚠ the GPU is unhealthy ({reason}): managed GPU containers are refused "
                "until a person clears it with POST /api/docker-gpu/clear — "
                "nothing resets the GPU automatically")

    def clear(self) -> None:
        self.unhealthy, self._at = None, float("-inf")


gpu = Gpu()
