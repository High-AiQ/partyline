"""Mention-based delivery routing for live attachments."""

import logging

from .mentions import mentioned_names

logger = logging.getLogger(__name__)


async def route_message(runtime, conv_id: str, message: dict) -> None:
    """Deliver direct mentions and @all messages to live attachments."""
    if message["sender_type"] == "system":
        return
    names = mentioned_names(message["body"])
    ring_all = "all" in names
    unreachable: list[str] = []
    failed: list[str] = []
    delivered: set[str] = set()
    queued: set[str] = set()
    for attachment in runtime.db.list_attachments(conv_id):
        directly_addressed = ring_all or attachment["name"].lower() in names
        if (
            not directly_addressed
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
            if not ring_all and attachment["name"] not in unreachable:
                unreachable.append(attachment["name"])
            continue
        try:
            if await runtime.deliver_pending(conv_id, attachment, adapter):
                delivered.add(attachment["name"].lower())
            else:
                queued.add(attachment["name"].lower())
        except OSError:
            logger.exception("pty wake delivery to @%s failed", attachment["name"])
            failed.append(attachment["name"])

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
    for name in failed:
        await runtime.post_message(
            conv_id,
            "system",
            "system",
            f"⚠ @{name} wake delivery failed before cursor credit — "
            "check peek and mention it again",
        )
