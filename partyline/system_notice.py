"""System notices with optional machine attribution."""

from .contracts import MessageEvent, MessageResponse
from .hierarchy import stamp_source


async def post_system_notice(runtime, conv_id: str, body: str, *, actor=None):
    """Post an operational notice, attributing machine-authored actions."""
    msg = runtime.db.add_message(conv_id, "system", "system", body)
    if getattr(actor, "kind", None) == "machine":
        msg = {**msg, **stamp_source(runtime.db, msg["id"], actor)}
    await runtime.broadcast(conv_id, MessageEvent(message=MessageResponse.model_validate(msg)))
    await runtime.route_mentions(conv_id, msg)
    return msg
