"""Host-owned callbacks for queued and transcript-confirmed deliveries."""

from __future__ import annotations

from .follow_routing import catch_up_messages


def delivery_hooks(runtime, conv_id: str, att_id: str):
    """Build one activation's held-wake and evidence-credit callbacks."""
    attachment = runtime.db.get_attachment(att_id) or {}
    runtime_owner = attachment.get("runtime_owner")

    async def flush_held(message_ids: list[int]) -> bool:
        live = runtime.live.get(att_id)
        if live is None:
            return False
        async with runtime.db.reserve_attachment_delivery(att_id, runtime_owner) as reserved:
            if not reserved:
                return False
            messages = runtime.db.messages_by_ids(conv_id, message_ids)
            delivery = catch_up_messages(attachment, messages)
            if messages and await live.deliver(delivery) is False:
                return False
            if messages and not runtime.db.set_last_seen(
                att_id, messages[-1]["id"], runtime_owner
            ):
                raise RuntimeError("attachment ownership changed during held delivery")
            runtime.db.clear_queued_delivery_ids(att_id, message_ids)
        return True

    async def persist_ids(message_ids: list[int]) -> bool:
        return await runtime.db.queue_delivery_ids(att_id, message_ids, runtime_owner)

    async def confirm_ids(message_ids: list[int]) -> bool:
        """Credit transcript-evidenced ids only to the activation that pasted them."""
        if not message_ids:
            return False
        async with runtime.db.reserve_attachment_delivery(att_id, runtime_owner) as reserved:
            if not reserved:
                return False
            if not runtime.db.set_last_seen(att_id, max(message_ids), runtime_owner):
                return False
            runtime.db.clear_queued_delivery_ids(att_id, message_ids)
        return True

    return (
        flush_held,
        lambda: runtime.db.queued_delivery_ids(att_id),
        persist_ids,
        confirm_ids,
    )
