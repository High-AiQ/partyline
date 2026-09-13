"""Mentions resolve across a line's tree, along the edges delegation runs on.

One tree is one mention namespace — `hierarchy.tree_live_name_conflict` keeps
each handle live on exactly one row — so ``@lead`` said on a child line has
one meaning even when the lead sits on the parent. Before this module that
mention reached nobody: the sub-manager's assignment arrived as ``[lead]:``,
it replied ``@lead done`` on its own line, the router found no such live row
there, and the tree went idle with both sides believing they had spoken. Three
days of a three-sub-line project recorded this dozens of times (`docs/lessons.md`).

Which edges carry a mention is the shape of the hierarchy, not the shape of
the tree, and crossing a line is a manager's act. A line's manager (or a
person) may reach any process on a descendant line — that is what
delegating down *is* — and the managers of the lines above it, which is how
it reports. An ordinary participant stays on its own line: it neither hears
from nor speaks to other lines, so "the lead is a true manager" holds and
an implementer cannot route around it. One that names a process elsewhere
is told where that process lives and whom to tell instead, because the
alternative — silence — is how siblings came to believe they shared a line.

A relay is a private copy on the target's own line: stamped with where it
was said, addressed to exactly that process (``audience_attachment_id``), so
it rides the target's ordinary cursor and digest, is shown to the humans
there, and costs no other process on that line any context. The copy is
foreign-sourced — its ``source_conv_id`` differs from its line — and a
foreign-sourced message is never relayed again, so a mention crosses the
tree at most once and two lines cannot start a ping-pong. ``@all`` stays a
one-line ring.
"""

from __future__ import annotations

from .contracts import MessageEvent, MessageResponse
from .hierarchy import ancestors, descendants, lead_attachment, tree_live_name_conflict

LIVE = ("starting", "running")


def is_foreign(message: dict) -> bool:
    """Said on another line: an API assignment from a parent, or a relay copy."""
    source = message.get("source_conv_id")
    return bool(source) and source != message.get("conv_id")


def speaker_attachment(db, conv_id: str, message: dict) -> dict | None:
    """The live row that said this, when a process did.

    Adapter speech is stored without a source stamp, so the handle is resolved
    against this line's live rows; the tree-unique name rule makes that
    unambiguous.
    """
    if message.get("source_attachment_id"):
        return db.get_attachment(message["source_attachment_id"])
    if message.get("sender_type") != "agent":
        return None
    wanted = str(message.get("sender") or "").lower()
    for att in db.list_attachments(conv_id):
        if att["status"] in LIVE and att["name"].lower() == wanted:
            return att
    return None


def may_cross(message: dict, speaker: dict | None) -> bool:
    return message.get("sender_type") == "human" or bool(speaker and speaker.get("is_lead"))


def resolve_elsewhere(db, conv_id: str, names: set[str], *, crossing: bool):
    """Live rows on other lines a mention from ``conv_id`` may address, and the
    handles it names that live on lines it may not — for the notice."""
    below, above = set(descendants(db, conv_id)), set(ancestors(db, conv_id))
    reached: list[dict] = []
    withheld: list[dict] = []
    for name in sorted(names - {"all"}):
        target = tree_live_name_conflict(db, conv_id, name)
        if target is None or target["conv_id"] == conv_id:
            continue
        line = target["conv_id"]
        allowed = crossing and (line in below or (line in above and target.get("is_lead")))
        (reached if allowed else withheld).append(target)
    return reached, withheld


def withheld_notice(db, conv_id: str, target: dict, crossing: bool) -> str:
    line = db.get_conversation(target["conv_id"]) or {}
    where = f"⚠ {target['name']} is on line «{line.get('name', '?')}», not this one — "
    if crossing:
        return where + "a captain reaches every process below it and only the captains above it"
    manager = lead_attachment(db, conv_id)
    whom = f"tell @{manager['name']}, your captain, instead" if manager else "this line has no captain"
    return where + f"only a line's captain talks to other lines; {whom}"


def reaches_a_process(db, speaker: dict, names: set[str]) -> bool:
    """Whether ``names`` includes a live process this speaker can actually ring:
    one on its own line, or one across an edge its role may cross."""
    names = names - {speaker["name"].lower()}
    if "all" in names:
        return True
    for att in db.list_attachments(speaker["conv_id"]):
        if att["status"] in LIVE and att["id"] != speaker["id"] and att["name"].lower() in names:
            return True
    reached, _ = resolve_elsewhere(
        db, speaker["conv_id"], names, crossing=bool(speaker.get("is_lead"))
    )
    return bool(reached)


async def post_private(
    runtime, line_id, sender, sender_type, body, *, audience, source=None, route=True
):
    """Post a message one process on ``line_id`` is shown, then route it there.

    ``source`` is ``(attachment id or None, line id)`` of where it was said.
    Routing is forced because the return path posts these as system notices.
    """
    copy = runtime.db.add_message(line_id, sender, sender_type, body)
    speaker_id, origin_id = source or (None, None)
    runtime.db._exec(
        "UPDATE messages SET source_attachment_id=?, source_conv_id=?,"
        " audience_attachment_id=? WHERE id=?",
        (speaker_id, origin_id, audience, copy["id"]),
    )
    origin = runtime.db.get_conversation(origin_id) if origin_id else None
    copy.update(
        source_attachment_id=speaker_id,
        source_conv_id=origin_id,
        source_conv_name=origin["name"] if origin else None,
        audience_attachment_id=audience,
    )
    await runtime.broadcast(line_id, MessageEvent(message=MessageResponse.model_validate(copy)))
    if route:
        await runtime.route_mentions(line_id, copy, force=True)
    return copy


async def relay_mentions(runtime, conv_id: str, message: dict, names: set[str]) -> set[str]:
    """Copy the message to each reachable process it names on another line.

    Returns the handles that live elsewhere in the tree, reached or not, so
    the caller keeps its "not attached" notice for handles that truly are.
    """
    if message.get("sender_type") == "system":
        return set()
    speaker = speaker_attachment(runtime.db, conv_id, message)
    crossing = may_cross(message, speaker)
    reached, withheld = resolve_elsewhere(runtime.db, conv_id, names, crossing=crossing)
    if is_foreign(message):
        return {att["name"].lower() for att in reached + withheld}
    for target in reached:
        if speaker is not None and target["id"] == speaker["id"]:
            continue
        await post_private(
            runtime, target["conv_id"], message["sender"], message["sender_type"],
            message["body"], audience=target["id"],
            source=(speaker["id"] if speaker else None, conv_id),
        )
    for target in withheld:
        notice = withheld_notice(runtime.db, conv_id, target, crossing)
        await runtime.post_message(conv_id, "system", "system", notice)
    return {att["name"].lower() for att in reached + withheld}
