"""Keep same-line jack state and every tab's line rail in one broadcast path."""

from .attachment_view import attach_bridge, attach_memory_usage, attachment_response
from .contracts import AttachmentEvent, CaptainChangedEvent, LineLiveEvent


async def broadcast_attachment_state(runtime, conv_id: str, att_id: str) -> None:
    """Emit the jack update and its line's derived live count together."""
    attachment = runtime.db.get_attachment(att_id)
    if attachment is None:
        return
    # A claim that lands between mentions releases old probes and immediately
    # retries their backlog through the normal readiness/idle delivery path.
    runtime.transcript_claimed(att_id, attachment.get("runtime_owner"))
    response = attach_bridge(attach_memory_usage(
        await attachment_response(attachment), runtime.memory_usage.get(att_id)
    ), runtime.db)
    if runtime.db.get_attachment(att_id) is None:
        return  # Removal may have completed while the git lookup was in flight.
    await runtime.broadcast(conv_id, AttachmentEvent(attachment=response))

    conversation = runtime.db.get_conversation(conv_id)
    if conversation is None:
        return
    event = LineLiveEvent(conversation_id=conv_id, live_count=conversation["live_count"])
    for socket_conv_id in tuple(runtime.sockets):
        await runtime.broadcast(socket_conv_id, event)


async def broadcast_captain(runtime, conv_id: str) -> None:
    """Send the current captain to the line and its ancestor views."""
    from .hierarchy import ancestors, lead_attachment

    lead = lead_attachment(runtime.db, conv_id)
    event = CaptainChangedEvent(conversation_id=conv_id, attachment_id=lead["id"] if lead else None)
    for line in [conv_id, *ancestors(runtime.db, conv_id)]:
        await runtime.broadcast(line, event)
