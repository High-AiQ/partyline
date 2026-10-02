"""Optional delivery-boundary hook used by runtimes that track paste credit."""

from __future__ import annotations


async def credit_at_turn_end(runtime, att_id: str, owner: str | None) -> None:
    callback = getattr(runtime, "credit_at_turn_end", None)
    if callback is not None:
        await callback(att_id, owner)
