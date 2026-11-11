"""Host-owned callbacks for queued and transcript-confirmed deliveries."""

from __future__ import annotations

from .delivery_reservation import reserve_delivery
from .delivery_credit_accounting import confirm_reserved


def delivery_hooks(runtime, conv_id: str, att_id: str):
    """Build one activation's held-wake and evidence-credit callbacks."""
    attachment = runtime.db.get_attachment(att_id) or {}
    runtime_owner = attachment.get("runtime_owner")

    async def flush_held(message_ids: list[int]) -> bool:
        live = runtime.live.get(att_id)
        if live is None:
            return False
        async with reserve_delivery(runtime.db, live, att_id, runtime_owner) as reserved:
            if not reserved:
                return False
            att = runtime.db.get_attachment(att_id) or {}
            last_seen = att.get("last_seen", 0)
            persisted = set(runtime.db.queued_delivery_ids(att_id))
            outstanding = set(runtime._live_uncredited(att_id, runtime_owner) or ())
            entry = runtime.uncredited.get(att_id) or {}
            if entry.get("claim_retry_pending"):
                outstanding.difference_update(entry.get("claim_ids", ()))
            deliverable_ids = [
                mid for mid in message_ids
                if mid not in outstanding and (mid in persisted or mid > last_seen)
            ]
            if outstanding.intersection(message_ids):
                return False
            runtime.db.clear_queued_delivery_ids(att_id, message_ids)
            if not deliverable_ids:
                return True
            messages = runtime.db.messages_by_ids(conv_id, deliverable_ids)
            if messages and await live.deliver(messages) is False:
                # A queue flush is still an unproved paste. Keep suppression
                # until its transcript receipt, including after the hello turn.
                runtime._record_unproved(att, live, messages)
                return False
            if messages and outstanding:
                runtime._record_unproved(att, live, messages)
                confirm_reserved(runtime, att_id, [m["id"] for m in messages], runtime_owner)
            elif messages and not runtime.db.set_last_seen(
                att_id, messages[-1]["id"], runtime_owner
            ):
                raise RuntimeError("attachment ownership changed during held delivery")
        return True

    async def persist_ids(message_ids: list[int]) -> bool:
        return await runtime.db.queue_delivery_ids(att_id, message_ids, runtime_owner)

    async def confirm_ids(message_ids: list[int]) -> bool:
        """Credit transcript-evidenced ids only to the activation that pasted them."""
        return await runtime.confirm_delivery_ids(att_id, message_ids, runtime_owner)

    async def credit_boundary() -> None:
        """Credit pending fallback deliveries at an adapter-declared boundary."""
        await runtime.credit_at_turn_end(att_id, runtime_owner)

    return (
        flush_held,
        lambda: runtime.db.queued_delivery_ids(att_id),
        persist_ids,
        confirm_ids,
        credit_boundary,
    )
