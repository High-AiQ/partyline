"""What became of the handles a routed message named that no live process took.

Split from ``message_routing``: relays to other lines, task fallbacks, the
"not attached" report and the person's unrecognised-handle notice. An agent
speaker gets everything it hit as one private, waking notice
(``unreached.Unreached``); a person keeps the notices on the line.
"""

from .mention_fallbacks import route_fallbacks
from .mention_relay import hint_root_captain, is_foreign, relay_mentions
from .mentions import known_mention_names, mentioned_names, quoted_names
from .unreached import explain, people, slips, unknown_handles, unreached_for


async def settle_mentions(
    runtime, conv_id: str, message: dict, names: set[str],
    unreachable: list[str], delivered: set[str], queued: set[str],
) -> None:
    """Report the ``names`` the delivery loop did not reach, as the speaker should hear it."""
    unreached = unreached_for(runtime.db, conv_id, message)
    if unreached is None or unreached.borrowed:  # a borrowed collector is sent by its owner
        return await _settle(runtime, conv_id, message, names, unreachable, delivered, queued, unreached)
    with unreached.collecting():
        await _settle(runtime, conv_id, message, names, unreachable, delivered, queued, unreached)
    await unreached.send(runtime, delivered | queued)


async def _settle(runtime, conv_id, message, names, unreachable, delivered, queued, unreached) -> None:
    db = runtime.db
    pending = names - delivered - queued
    # A handle live on a related line is reached there, not reported missing.
    elsewhere = await relay_mentions(runtime, conv_id, message, pending, unreached)
    elsewhere |= await route_fallbacks(runtime, conv_id, message, pending - elsewhere, unreached)
    rest = pending - elsewhere
    unavailable = [
        name
        for name in unreachable
        if name.lower() not in delivered
        and name.lower() not in queued
        and name.lower() not in elsewhere
    ]
    foreign = is_foreign(message)  # mail: the line it was said on has already told its speaker
    gone = {}
    if unreached is not None and "all" not in names and not foreign \
            and not message.get("audience_attachment_id"):
        # A detached task worker on any line, however it was named, is one a speaker must hear about.
        gone = {name: why for name in sorted(rest - {"all", unreached.speaker["name"].lower()}
                                   - {name.lower() for name in unavailable})
                if (why := explain(db, conv_id, name, unreached.speaker["id"]))}
    # A name written only as code was quoted, and a message that reached someone
    # was handed off: neither wakes its speaker over a stray ``@word``. A notice
    # that is going out anyway carries every unknown name, at no extra wake.
    quoted = quoted_names(message["body"])
    handed_off = bool(delivered or queued or elsewhere or "all" in names or names & people(db))
    if unreached is not None and (unreached.lines or gone or unavailable):
        handed_off = False
    unsaid = rest - set(gone) - quoted
    unknown: dict[str, str | None] = {}
    if unreached is not None and not foreign and not message.get("audience_attachment_id"):
        # Every agent hears of a handle nobody wears, not only a task's worker.
        unknown = slips(db, conv_id, unknown_handles(
            db, conv_id, unsaid - {unreached.speaker["name"].lower()}), handed_off)
        unsaid = {name for name, close in unknown.items() if not close}
    reported: set[str] = set()
    if message["sender_type"] == "agent":
        reported = await hint_root_captain(
            runtime, conv_id, message, unsaid, None if foreign else unreached)
    for name, close in unknown.items():
        if close == name:
            unreached.add(f"@{name}", "no live process you can reach wears that handle now; "
                          "nothing was delivered")
        elif close:
            unreached.add(f"@{name}", f"unknown handle — did you mean @{close}? Nothing was "
                          "delivered for this name")
    plain = sorted(name for name, close in unknown.items() if not close and name not in reported)
    if plain:
        unreached.add(", ".join(f"@{name}" for name in plain),
                      "unknown handle — nobody here or reachable is called that; check the "
                      "spelling (line names and task handles are not mentionable)")
    if unreached is not None:
        for name, why in gone.items():
            unreached.add(name, why)
        for name in unavailable:
            unreached.add(name, explain(db, conv_id, name, unreached.speaker["id"]) or "not attached")
    elif not message.get("bridge_id"):
        for name in unavailable:
            await runtime.post_message(
                conv_id,
                "system",
                "system",
                f"⚠ @{name} was mentioned but is not attached — nothing was delivered",
            )
    if (
        message["sender_type"] == "human"
        and not delivered
        and not queued
        and not elsewhere
        and "all" not in names
    ):
        mentioned = mentioned_names(message["body"])
        unrecognized = mentioned - known_mention_names(db, conv_id, mentioned)
        if unrecognized:
            handles = ", ".join(f"@{name}" for name in sorted(unrecognized))
            await runtime.post_message(
                conv_id,
                "system",
                "system",
                f"⚠ nobody live on this line is named {handles} — nothing was delivered",
            )
