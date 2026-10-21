"""The root captain's side of its talk with task processes stays off the root transcript.

A message the root captain posts on an orchestrator root line, whose every
mention is a process on one of that root's task lines, is the other half of the
exchange `task_private` already hides when a task process answers: people read
it on the task line, where the relay copy stays visible. A message that also
names a person or a root-line process, names no one, or says ``@all`` stays.
"""

from .mention_relay import speaker_attachment
from .mentions import mentioned_names


def is_task_only(db, conv_id: str, message: dict) -> bool:
    if message.get("sender_type") != "agent":
        return False
    speaker = speaker_attachment(db, conv_id, message)
    if not (speaker and speaker.get("is_lead") and speaker["conv_id"] == conv_id):
        return False
    names = mentioned_names(message.get("body") or "")
    if not names or "all" in names:
        return False
    task_names = {
        row["name"].lower() for row in db._exec(
            "SELECT a.name FROM attachments a JOIN task_reviews t ON t.conv_id=a.conv_id"
            " WHERE t.root_id=?", (conv_id,))}
    return names <= task_names


def hidden_from_people(db, conv_id: str, event) -> bool:
    """Whether this fan-out event is never shown on the line: bridge traffic or a task-only message."""
    message = getattr(event, "message", None)
    if message is None:
        return False
    if getattr(message, "bridge_id", None):
        return True
    return message.sender_type == "agent" and hide_if_task_only(db, conv_id, message.model_dump())


def hide_if_task_only(db, conv_id: str, message: dict) -> bool:
    """Mark the message ``task_private`` when it is task-only; true when it was hidden."""
    if not is_task_only(db, conv_id, message):
        return False
    db._exec("UPDATE messages SET task_private=1 WHERE id=?", (message["id"],))
    return True
