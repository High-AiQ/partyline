"""An explicit resume carries its backlog the way recovery does: staged, never pasted blind.

Recovery after a restart hands a resumed codex its unread messages as the
positional prompt of ``codex resume``, because the TUI drops input pasted
before it is ready — a resumed session shows an "interrupted" banner that
eats the first Enter. The explicit resume route did not: it spawned with no
backlog, and the first mention routed to the new process pasted at t=0 and
sat unsent in the composer until a person pressed Enter (luna, 10:19 today).

So the route now reads the backlog first — including the "continue where
you left off" notice for a process cut mid-turn — and lets the adapter stage
it. An adapter that cannot stage gets the backlog once it reports ready.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import HTTPException

from . import turn_marker
from .continuation_delivery import deliver_continuation
from .reattach import READY_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)
_SETTLING: set[asyncio.Task] = set()


async def resume_with_backlog(runtime, att_id: str, resume, *, timeout=READY_TIMEOUT_SECONDS):
    att = runtime.db.get_attachment(att_id)
    if att is None:
        raise HTTPException(404)
    await turn_marker.announce_if_interrupted(runtime, att)
    pending = runtime.db.messages_after(att["conv_id"], att["last_seen"], att["name"], att_id)
    resumed = await resume(att_id, pending)
    if pending:
        task = asyncio.create_task(_settle(runtime, resumed, att_id, pending, timeout))
        _SETTLING.add(task)
        task.add_done_callback(_SETTLING.discard)
    return resumed


async def _settle(runtime, resumed, att_id: str, pending: list[dict], timeout: float) -> None:
    adapter = resumed.adapter
    try:
        if resumed.startup_delivery_staged:
            # Process creation proves intent; the structured transcript proves receipt.
            if await asyncio.wait_for(adapter.wait_startup_delivery_received(), timeout):
                runtime.db.set_last_seen(att_id, pending[-1]["id"], adapter.att.get("runtime_owner"))
        elif await asyncio.wait_for(adapter.wait_ready(), timeout):
            await deliver_continuation(runtime, adapter, att_id, pending, timeout)
    except (TimeoutError, RuntimeError) as exc:
        # Slow is not failed: the next mention delivers whatever is still unread.
        logger.info("resume backlog for %s not settled: %s", att_id, exc)


async def drain() -> None:
    """Wait for every in-flight backlog to settle — for tests."""
    if _SETTLING:
        await asyncio.gather(*_SETTLING, return_exceptions=True)
