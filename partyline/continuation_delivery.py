"""Continuation delivery whose credit may arrive after the pty write."""

from __future__ import annotations

import asyncio


async def deliver_continuation(runtime, adapter, att_id: str, messages: list[dict], timeout: float):
    """Write under the owner lock, then await any structured receipt outside it."""
    owner = adapter.att.get("runtime_owner")
    message_ids = [message["id"] for message in messages]
    async with runtime.db.reserve_attachment_delivery(att_id, owner) as reserved:
        if not reserved:
            raise RuntimeError("attachment ownership changed before continuation delivery")
        prepare = getattr(adapter, "prepare_delivery_receipt", None)
        if prepare is not None:
            prepare(message_ids)
        pasted = await adapter.deliver(messages)
        if pasted is not False:
            if not runtime.db.set_last_seen(att_id, messages[-1]["id"], owner):
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
