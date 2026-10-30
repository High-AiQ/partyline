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
from .line_depth import live_workers
from .mentions import known_mention_names
from .message_visibility import is_reaction_notice
from .task_ack_limit import RULE, withheld_ack
from .task_mention_guard import notify_cross_task, split_cross_task
from .resume_backlog import WORKER_PACK_NOTICE_PREFIX

LIVE = ("starting", "running")


def live_manager(runtime, conv_id: str) -> dict | None:
    """The line's manager, only if a message could actually reach it.

    The same three conditions `message_routing` uses, deliberately: status
    exactly ``running``, a live adapter, and an activation that still matches.
    A ``starting`` or superseded manager is not delivery — posting at one
    would mark the report notified while nobody was woken, which is the
    silence this whole path exists to avoid.
    """
    lead = lead_attachment(runtime.db, conv_id)
    if lead is None or lead["status"] != "running":
        return None
    adapter = runtime.live.get(lead["id"])
    if adapter is None or not runtime.activation_matches(adapter, lead):
        return None
    return lead


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


def task_root_captain(db, conv_id: str) -> dict | None:
    """The live lead of the root line a task line belongs to, if this is one."""
    row = db._exec("SELECT root_id FROM task_reviews WHERE conv_id=?", (conv_id,)).fetchone()
    lead = lead_attachment(db, row["root_id"]) if row else None
    return lead if lead and lead["status"] in LIVE else None


def is_task_to_root(db, from_conv: str, to_conv: str) -> bool:
    """A task line's mention reaching its own root line: people read it on the task line."""
    return db._exec("SELECT 1 FROM task_reviews WHERE conv_id=? AND root_id=?",
                    (from_conv, to_conv)).fetchone() is not None


def may_cross(message: dict, speaker: dict | None) -> bool:
    return message.get("sender_type") == "human" or bool(speaker and speaker.get("is_lead"))


def resolve_elsewhere(db, conv_id: str, names: set[str], *, crossing: bool):
    """Live rows on other lines a mention from ``conv_id`` may address, and the
    handles it names that live on lines it may not — for the notice."""
    below, above = set(descendants(db, conv_id)), set(ancestors(db, conv_id))
    root = task_root_captain(db, conv_id)
    reached: list[dict] = []
    withheld: list[dict] = []
    for name in sorted(names - {"all"}):
        target = tree_live_name_conflict(db, conv_id, name)
        if target is None or target["conv_id"] == conv_id:
            continue
        line = target["conv_id"]
        allowed = crossing and (line in below or (line in above and target.get("is_lead")))
        allowed = allowed or bool(root and target["id"] == root["id"])
        (reached if allowed else withheld).append(target)
    return reached, withheld


def withheld_notice(db, conv_id: str, target: dict, crossing: bool) -> str:
    line = db.get_conversation(target["conv_id"]) or {}
    where = f"⚠ {target['name']} is on line «{line.get('name', '?')}», not this one — "
    if crossing:
        return where + "a captain reaches every process below it and only the captains above it"
    manager = lead_attachment(db, conv_id)
    root = task_root_captain(db, conv_id)
    if manager:
        whom = f"tell @{manager['name']}, your captain, instead"
    elif root:
        whom = f"tell @{root['name']}, the root captain, instead"
    else:
        whom = "this line has no captain"
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
    runtime, line_id, sender, sender_type, body, *, audience, source=None, actor=None, route=True,
    private=False,
):
    """Post a message one process on ``line_id`` is shown, then route it there.

    ``source`` is ``(attachment id or None, line id)`` of where it was said.
    Routing is forced because the return path posts these as system notices.
    """
    copy = runtime.db.add_message(line_id, sender, sender_type, body)
    speaker_id, origin_id = source or (None, None)
    if source is None and getattr(actor, "kind", None) == "machine":
        speaker_id, origin_id = actor.attachment_id, actor.conv_id
    runtime.db._exec(
        "UPDATE messages SET source_attachment_id=?, source_conv_id=?,"
        " audience_attachment_id=?, task_private=? WHERE id=?",
        (speaker_id, origin_id, audience, int(private), copy["id"]),
    )
    origin = runtime.db.get_conversation(origin_id) if origin_id else None
    copy.update(
        source_attachment_id=speaker_id,
        source_conv_id=origin_id,
        source_conv_name=origin["name"] if origin else None,
        audience_attachment_id=audience,
    )
    # A reaction notice is one process's mail: no reply is needed unless it
    # raises something new. Browsers already see the reaction itself on the
    # message, so the fan-out skips the copy while forced routing still wakes
    # the addressed process.
    if not (private or is_reaction_notice(copy)):
        await runtime.broadcast(line_id, MessageEvent(message=MessageResponse.model_validate(copy)))
    if route:
        await runtime.route_mentions(line_id, copy, force=True)
    return copy


async def ring_workers(runtime, line_id: str, captain: dict) -> dict | None:
    """Wake every live non-captain process on ``line_id`` once, as workers.

    A worker attached before its captain was appointed never got the worker
    pack at join, and the rider only carries it on the worker's next wake —
    which, left to itself, might be the worker self-assigning from the goal.
    One routed @mention per worker makes that next wake happen now.
    """
    workers = [att for att in live_workers(runtime.db, line_id)
               if att["id"] != captain["id"] and att["id"] in runtime.live]
    if not workers:
        return None
    names = " ".join(f"@{att['name']}" for att in workers)
    msg = await runtime.post_message(  # the captain is named bare: every @ rings
        line_id, "system", "system",
        f"{WORKER_PACK_NOTICE_PREFIX}{names}: {captain['name']} is now this line's captain — wait for your "
        "captain's @mention before editing anything; the worker pack rides this wake",
    )
    await runtime.route_mentions(line_id, msg, force=True)
    return msg


async def hint_root_captain(runtime, conv_id: str, message: dict, unresolved: set[str]) -> None:
    """Tell a task process whom to mention when its @name reached nobody, and
    file the same once-per-handle incident notice the API refusal sends."""
    speaker = speaker_attachment(runtime.db, conv_id, message)
    root = task_root_captain(runtime.db, conv_id)
    if speaker is None or root is None or speaker["id"] == root["id"]:
        return
    unresolved = unresolved - {speaker["name"].lower()}
    unresolved -= known_mention_names(runtime.db, conv_id, unresolved)
    # The parser offers both the literal spelling and the spelling without
    # trailing punctuation. Do not call the literal spelling a ghost when
    # the other spelling already names a process or person.
    stripped = {name.rstrip(".-_") for name in unresolved}
    known = known_mention_names(runtime.db, conv_id, stripped)
    unresolved = {name for name in unresolved if name.rstrip(".-_") not in known}
    if not unresolved:
        return
    handles = ", ".join(f"@{name}" for name in sorted(unresolved))
    if root["name"].lower() in unresolved:
        body = (f"⚠ {handles} reached nobody — the root captain could not be routed; "
                "check the captain's connection and retry")
    else:
        body = (f"⚠ {handles} reached nobody — line names are not mentionable; "
                f"to reach the root captain, mention @{root['name']}")
    await post_private(
        runtime, conv_id, "system", "system",
        body,
        audience=speaker["id"], route=False,
    )
    from .task_ghost_mentions import report_ghost_incidents  # it imports this module
    await report_ghost_incidents(runtime, conv_id, speaker, unresolved)


async def relay_mentions(runtime, conv_id: str, message: dict, names: set[str]) -> set[str]:
    """Copy the message to each reachable process it names on another line.

    Returns the handles that live elsewhere in the tree, reached or not, so
    the caller keeps its "not attached" notice for handles that truly are.
    """
    if message.get("sender_type") == "system":
        return set()
    speaker = speaker_attachment(runtime.db, conv_id, message)
    if speaker is not None:
        names = names - {speaker["name"].lower()}
    crossing = may_cross(message, speaker)
    reached, withheld = resolve_elsewhere(runtime.db, conv_id, names, crossing=crossing)
    crossed: list[dict] = []
    if not message.get("audience_attachment_id"):
        # The guard is for speech on this line. A copy addressed to one process
        # — a relay or a message_task — is mail, not speech: re-guarding it rang
        # the speaker once per copy per other named handle, so one root-line
        # reply mentioning three workers cost six held-back notices, every one
        # false, for copies that had just been delivered.
        crossed, withheld = split_cross_task(runtime.db, conv_id, speaker, withheld)
        await notify_cross_task(runtime, conv_id, speaker, crossed)
    withheld_all = withheld + crossed
    if is_foreign(message):
        return {att["name"].lower() for att in reached + withheld_all}
    for target in reached:
        if speaker is not None and target["id"] == speaker["id"]:
            continue
        if speaker is not None and withheld_ack(runtime.db, conv_id, target["conv_id"], message):
            await post_private(runtime, conv_id, "system", "system",
                               f"⚠ @{target['name']}: {RULE}", audience=speaker["id"], route=False)
            continue
        await post_private(
            runtime, target["conv_id"], message["sender"], message["sender_type"],
            message["body"], audience=target["id"],
            source=(speaker["id"] if speaker else None, conv_id),
            private=is_task_to_root(runtime.db, conv_id, target["conv_id"]),
        )
    for target in withheld:
        notice = withheld_notice(runtime.db, conv_id, target, crossing)
        await runtime.post_message(conv_id, "system", "system", notice)
    return {att["name"].lower() for att in reached + withheld_all}
