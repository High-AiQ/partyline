"""Archive a line together with everything beneath it, deepest line first.

A person at the root of a finished project should not have to unlink or
archive each child by hand; the delete dialog offers the whole tree in one
checkbox. Children go first so that at no point does an archived parent hold
a live child, which is the state the one-line route refuses.
"""

from __future__ import annotations

from .contracts import ConversationArchivedEvent, ConversationDeletedEvent
from .hierarchy import descendants


async def archive_line(runtime, conv_id: str) -> list[str]:
    """Archive one line: announce it, stop its processes, mark it. Returns handles stopped."""
    await runtime.broadcast(conv_id, ConversationArchivedEvent(conversation_id=conv_id))
    await runtime.broadcast(conv_id, ConversationDeletedEvent(conversation_id=conv_id))
    stopped = await runtime.stop_attachments(conv_id)
    runtime.db.archive_conversation(conv_id)
    runtime.sockets.pop(conv_id, None)
    return stopped


async def archive_subtree(runtime, conv_id: str) -> tuple[list[str], list[str]]:
    """Archive every live descendant, deepest first, then the line itself.

    Returns ``(handles stopped, line ids archived)`` in the order taken.
    """
    stopped: list[str] = []
    archived: list[str] = []
    below = [
        line_id for line_id in reversed(descendants(runtime.db, conv_id))
        if not (runtime.db.get_conversation(line_id) or {}).get("archived_at")
    ]
    for line_id in [*below, conv_id]:
        stopped.extend(await archive_line(runtime, line_id))
        archived.append(line_id)
    return stopped, archived
