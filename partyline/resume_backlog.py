"""Select messages an attachment should receive when it resumes."""

from __future__ import annotations

from .message_queries import MESSAGE_SELECT, as_message
from .mentions import known_mention_names, line_addressed, mentioned_names
from .solo_line import implied_addressee

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
        audience = message.get("audience_attachment_id")
        if audience:
            return audience == att["id"]
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
            and not known_mention_names(runtime.db, att["conv_id"], names)
        )

    selected = [message for message in pending if addressed(message)]
    latest_non_system = runtime.db._exec(
        MESSAGE_SELECT +
        " WHERE m.conv_id=? AND m.sender_type!='system' ORDER BY m.id DESC LIMIT 1",
        (att["conv_id"],),
    ).fetchone()
    if latest_non_system is not None:
        latest = as_message(latest_non_system)
        if (
            latest.get("sender_type") == "human"
            and latest["id"] not in {message["id"] for message in selected}
            and addressed_human_message(runtime, att, latest)
        ):
            selected.append(latest)
    return sorted({message["id"]: message for message in selected}.values(), key=lambda m: m["id"])


def addressed_human_message(runtime, att: dict, message: dict) -> bool:
    """Whether the human message would route to this attachment on this line."""
    audience = message.get("audience_attachment_id")
    if audience:
        return audience == att["id"]
    body = str(message.get("body") or "")
    names = mentioned_names(body)
    name = att["name"].lower()
    # The resumed process can be treated as live for a plain message only
    # when this is its line's sole attachment. With inactive siblings, the
    # historical live roster at the time of the message is not recorded.
    include_attachment_id = (
        att["id"]
        if len(runtime.db.list_attachments(att["conv_id"])) == 1
        else None
    )
    return (
        name in names
        or "all" in names
        or name in line_addressed(body)
        or implied_addressee(
            runtime.db, message, include_attachment_id=include_attachment_id
        ) == name
    )
