"""Lifetime of managed containers: past ``partyline.max-seconds`` the inventory stops them.

Stops, never removes, so the container's outputs survive; the owning line is told once.
"""

from __future__ import annotations

import logging
import time

from . import docker_api
from .system_notice import post_system_notice

logger = logging.getLogger(__name__)
_told: set[str] = set()


def overdue(containers: list[dict], now: float) -> list[dict]:
    return [c for c in containers if c["state"] == "running" and c["managed"] and c["max_seconds"]
            and c["started_at"] and now - c["started_at"] > c["max_seconds"]]


async def enforce_lifetimes(runtime, containers: list[dict], now: float | None = None) -> None:
    now = time.time() if now is None else now
    for c in overdue(containers, now):
        try:
            status, _body = await docker_api.request("POST", f"/containers/{c['id']}/stop?t=10", timeout=30.0)
        except (OSError, TimeoutError) as exc:
            logger.warning("docker lifetime: cannot stop %s: %s", c["id"][:12], exc)
            continue
        known = runtime.db.get_conversation(c["conversation_id"])
        if c["id"] in _told or status not in (204, 304) or not known:
            continue
        _told.add(c["id"])
        await post_system_notice(
            runtime, c["conversation_id"],
            f"⏹ container {c['name']} ({c['id'][:12]}) ran past its declared lifetime of "
            f"{c['max_seconds']} s and was stopped (stopped, not removed; its outputs are intact)")
