"""Persist a screen frame as a line media message, shared by screen_frame and agent actions."""

from .contracts import MessageEvent, MessageResponse
from .media import prepared_files
from .media_digest import digest_body


async def store_frame(runtime, store, conv_id: str, sender: str, data: bytes, mime: str,
                      caption: str):
    """Store one image and broadcast its digest message; returns the file reference."""
    prepared = prepared_files([(data, "screen-frame", mime)])
    message = runtime.db.add_message(conv_id, sender, "agent", "")
    try:
        refs = store.store(conv_id, message["id"], prepared, "Screen frame", None)
    except Exception:
        runtime.db._exec("DELETE FROM messages WHERE id=?", (message["id"],))
        raise
    body = digest_body(caption, refs, "")
    runtime.db._exec("UPDATE messages SET body=? WHERE id=?", (body, message["id"]))
    await runtime.broadcast(conv_id, MessageEvent(message=MessageResponse.model_validate(
        {**message, "body": body, "files": refs})))
    return refs[0]
