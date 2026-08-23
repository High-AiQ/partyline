"""Keep same-line jack state and every tab's line rail in one broadcast path."""

from .attachment_view import attachment_response
from .contracts import AttachmentEvent, LineLiveEvent


async def broadcast_attachment_state(runtime, conv_id: str, att_id: str) -> None:
    """Emit the jack update and its line's derived live count together."""
    attachment = runtime.db.get_attachment(att_id)
    if attachment is None:
        return
    response = await attachment_response(attachment)
    await runtime.broadcast(conv_id, AttachmentEvent(attachment=response))

    conversation = runtime.db.get_conversation(conv_id)
    if conversation is None:
        return
    event = LineLiveEvent(conversation_id=conv_id, live_count=conversation["live_count"])
    for socket_conv_id in tuple(runtime.sockets):
        await runtime.broadcast(socket_conv_id, event)
