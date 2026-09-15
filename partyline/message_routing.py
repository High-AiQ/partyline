"""Mention-based delivery routing for live attachments."""

import logging

from .interrupts import interrupt_for
from .mention_relay import relay_mentions
from .mentions import interrupt_names, line_addressed, mentioned_names
from .solo_line import implied_addressee

logger = logging.getLogger(__name__)


async def route_message(
    runtime, conv_id: str, message: dict, *, force: bool = False
) -> None:
    """Deliver direct mentions and @all messages to live attachments.

    System notices are not routed unless the caller says so: most of them
    name a process only to describe it. ``force`` is for the few the server
    writes *to* a process — the return path's "your worker went quiet".
    """
    if message["sender_type"] == "system" and not force:
        return
    names = mentioned_names(message["body"])
    # "worker: take the review" is an address when worker is live here.
    colon = line_addressed(message["body"])
    if colon:
        names |= {a["name"].lower() for a in runtime.db.list_attachments(conv_id)
                  if a["name"].lower() in colon and a["status"] in ("starting", "running")}
    # A person's plain message on a line with one live process is for it.
    if alone := implied_addressee(runtime.db, message):
        names.add(alone)
    # `@!name` is an operator's "stop and read this". Only a human may write
    # it: an agent's reply wakes other agents, so an agent-authored bang would
    # let the room cancel its own work in a loop.
    bangs = (
        interrupt_names(message["body"])
        if message["sender_type"] == "human"
        else set()
    )
    ring_all = "all" in names
    notices: list[str] = []
    unreachable: list[str] = []
    failed: list[str] = []
    delivered: set[str] = set()
    queued: set[str] = set()
    audience = message.get("audience_attachment_id")
    for attachment in runtime.db.list_attachments(conv_id):
        if audience and attachment["id"] != audience:
            continue  # a private copy rings the one process it exists for
        directly_addressed = ring_all or attachment["name"].lower() in names
        source = message.get("source_attachment_id")
        same_speaker = (
            source == attachment["id"]
            if source
            else attachment["name"].lower() == message["sender"].lower()
        )
        if not directly_addressed or same_speaker:
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
        if attachment["name"].lower() in bangs:
            # Interrupt first, report after: a notice posted before delivery
            # would ride the very digest it is describing.
            notices.append((await interrupt_for(attachment, adapter)).notice)
        try:
            if await runtime.deliver_pending(conv_id, attachment, adapter):
                delivered.add(attachment["name"].lower())
            else:
                queued.add(attachment["name"].lower())
        except OSError:
            logger.exception("pty wake delivery to @%s failed", attachment["name"])
            failed.append(attachment["name"])

    for notice in notices:
        await runtime.post_message(conv_id, "system", "system", notice)

    # A handle live on a related line is reached there, not reported missing.
    elsewhere = await relay_mentions(runtime, conv_id, message, names - delivered - queued)
    unavailable = [
        name
        for name in unreachable
        if name.lower() not in delivered
        and name.lower() not in queued
        and name.lower() not in elsewhere
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
