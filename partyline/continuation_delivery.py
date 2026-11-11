"""Continuation delivery whose credit may arrive after the pty write."""

from __future__ import annotations

import asyncio
import logging

from .delivery_reservation import reserve_delivery


async def deliver_continuation(runtime, adapter, att_id: str, messages: list[dict], timeout: float):
    """Write under the owner lock, then await any structured receipt outside it."""
    owner = adapter.att.get("runtime_owner")
    message_ids = [message["id"] for message in messages]
    async with reserve_delivery(runtime.db, adapter, att_id, owner) as reserved:
        if not reserved:
            raise RuntimeError("attachment ownership changed before continuation delivery")
        prepare = getattr(adapter, "prepare_delivery_receipt", None)
        if prepare is not None:
            prepare(message_ids)
        pasted = await adapter.deliver(messages)

    if pasted is not False:
        if not await runtime.confirm_delivery_ids(att_id, message_ids, owner):
            raise RuntimeError("attachment ownership changed during continuation delivery")
        return

    wait = getattr(adapter, "wait_delivery_received", None)
    if wait is None or not await asyncio.wait_for(wait(message_ids), timeout=timeout):
        raise RuntimeError("the process exited before accepting its continuation")
    attachment = runtime.db.get_attachment(att_id)
    if (
        attachment is None
        or attachment.get("runtime_owner") != owner
        or attachment["last_seen"] < messages[-1]["id"]
    ):
        raise RuntimeError("continuation receipt did not credit the current activation")


logger = logging.getLogger(__name__)
_CONTINUATIONS: set[asyncio.Task] = set()


async def staged_receipt(runtime, adapter, att_id: str, messages: list[dict]) -> bool:
    """Credit staged mail when its transcript receipt arrives, even after a timeout."""
    if not await adapter.wait_startup_delivery_received():
        return False
    return await runtime.confirm_delivery_ids(
        att_id, [message["id"] for message in messages], adapter.att.get("runtime_owner")
    )


def _track(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _CONTINUATIONS.add(task)

    def finished(done):
        _CONTINUATIONS.discard(done)
        if not done.cancelled() and (exc := done.exception()) is not None:
            logger.warning("resume continuation failed", exc_info=(type(exc), exc, exc.__traceback__))

    task.add_done_callback(finished)
    return task


def track_staged_receipt(runtime, adapter, att_id: str, messages: list[dict]) -> asyncio.Task:
    """Keep a recovery receipt waiter alive while the coordinator advances."""
    return _track(staged_receipt(runtime, adapter, att_id, messages))


async def continuation_after_ready(runtime, adapter, att_id: str, messages: list[dict], timeout: float):
    """Wait as long as necessary for readiness, then deliver the reserved batch."""
    if not await adapter.wait_ready():
        return False
    await deliver_continuation(runtime, adapter, att_id, messages, timeout)
    return True


def track_continuation(runtime, adapter, att_id: str, messages: list[dict], timeout: float) -> asyncio.Task:
    return _track(continuation_after_ready(runtime, adapter, att_id, messages, timeout))
