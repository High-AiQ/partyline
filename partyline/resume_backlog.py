"""Select messages an attachment should receive when it resumes."""

from __future__ import annotations

from .mentions import line_addressed, mentioned_names

WORKER_PACK_NOTICE_PREFIX = "☏ workers "


def addressed_backlog(runtime, att: dict, *, include_message_ids=()) -> list[dict]:
    """Return unread messages addressed to this process, plus explicit context."""
    pending = runtime.db.messages_after(
        att["conv_id"], att["last_seen"], att["name"], att["id"]
    )
    name = att["name"].lower()
    included = set(include_message_ids)
    attachments = runtime.db.list_attachments(att["conv_id"])
    solo = len(attachments) == 1 and attachments[0]["id"] == att["id"]

    def addressed(message: dict) -> bool:
        if message["id"] in included:
            return True
        if message.get("audience_attachment_id") == att["id"]:
            return True
        body = str(message.get("body") or "")
        names = mentioned_names(body)
        if message.get("sender_type") == "system":
            return (
                body.startswith(WORKER_PACK_NOTICE_PREFIX)
                and name in names
            )
        if name in names or "all" in names or name in line_addressed(body):
            return True
        return (
            solo
            and message.get("sender_type") == "human"
            and not message.get("audience_attachment_id")
            and not names
        )

    return [message for message in pending if addressed(message)]
