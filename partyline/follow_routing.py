"""Follower trigger policy and the synthetic catch-up label for CLI delivery."""

from collections.abc import Callable

from .mentions import addresses, mentioned_names

CATCH_UP_HEADER = "here's what you missed — bundled context, not a new instruction"


def follow_routes_message(
    attachment: dict, message: dict, is_working: Callable[[str], bool]
) -> bool:
    """Humans wake an idle follower; agent chatter only joins an open cycle."""
    return bool(attachment.get("follow")) and (
        message.get("sender_type") == "human" or is_working(attachment["id"])
    )


def catch_up_messages(attachment: dict, messages: list[dict]) -> list[dict]:
    """Label a follower batch containing traffic that did not directly address it."""
    name = str(attachment.get("name") or "")
    if not attachment.get("follow") or not any(
        not addresses(name, [message]) for message in messages
    ):
        return messages
    header = {"sender": "partyline", "sender_type": "system", "body": CATCH_UP_HEADER}
    return [header, *messages]


async def route_message(runtime, conv_id: str, message: dict) -> None:
    """Deliver direct mentions and hybrid follower traffic to live attachments."""
    if message["sender_type"] == "system":
        return
    names = mentioned_names(message["body"])
    ring_all = "all" in names
    unreachable: list[str] = []
    delivered: set[str] = set()
    queued: set[str] = set()
    for attachment in runtime.db.list_attachments(conv_id):
        directly_addressed = ring_all or attachment["name"].lower() in names
        follow_addressed = follow_routes_message(
            attachment, message, runtime.is_attachment_working
        )
        if (
            not (directly_addressed or follow_addressed)
            or attachment["name"].lower() == message["sender"].lower()
        ):
            continue
        adapter = (
            runtime.live.get(attachment["id"])
            if attachment["status"] == "running"
            else None
        )
        if adapter is not None and not runtime.activation_matches(adapter, attachment):
            queued.add(attachment["name"].lower())
            continue
        if adapter is None:
            if attachment["id"] in runtime.reattaching:
                queued.add(attachment["name"].lower())
                continue
            if directly_addressed and not ring_all and attachment["name"] not in unreachable:
                unreachable.append(attachment["name"])
            continue
        if await runtime.deliver_pending(conv_id, attachment, adapter):
            delivered.add(attachment["name"].lower())
        else:
            queued.add(attachment["name"].lower())

    unavailable = [
        name
        for name in unreachable
        if name.lower() not in delivered and name.lower() not in queued
    ]
    for name in unavailable:
        await runtime.post_message(
            conv_id,
            "system",
            "system",
            f"⚠ @{name} was mentioned but is not attached — nothing was delivered",
        )
