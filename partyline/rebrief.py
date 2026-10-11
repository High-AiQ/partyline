"""The post-compaction re-briefing a Claude Code worker prints into context.

`SessionStart(compact)` stdout is appended to the model's context, so it is
the one hook whose output matters: after a compaction the worker's context is
whatever its summary kept — not the acceptance criteria, not the assignment.
This renders the partyline side of what it should know: the goal, the line's
standing topic, and the newest message that actually assigned it work,
verbatim. Capped: the harness folds the whole stdout into context, so a
chatty topic must not eat the budget either.
"""

from __future__ import annotations

from .mentions import addresses
from .role_briefing import WORKER_REMINDER

REBRIEF_LIMIT = 4000


def latest_assignment(db, att: dict, scan: int = 300,
                      person_only: bool = False) -> str | None:
    """The newest line message that @mentions this process and may assign it.

    A person always may; an agent may when its source attachment is a lead —
    unless ``person_only``, which is the captain's rule: a captain takes
    work from the person alone. A sibling worker's @mention is conversation,
    not an assignment, and never survives a compaction on its own say-so.
    """
    name = (att.get("name") or "").lower()
    rows = db._exec(
        "SELECT sender, sender_type, source_attachment_id, body FROM messages "
        "WHERE conv_id=? AND sender_type IN ('human','agent') AND audience_attachment_id "
        "IS NULL ORDER BY id DESC LIMIT ?", (att["conv_id"], scan)).fetchall()
    for row in rows:
        if row["sender_type"] == "agent":
            if person_only:
                continue
            source = db.get_attachment(row["source_attachment_id"]) \
                if row["source_attachment_id"] else None
            if not source or not source.get("is_lead"):
                continue
        if addresses(name, [dict(row)]):
            return row["body"]
    return None


def render_rebrief(db, att: dict, limit: int = REBRIEF_LIMIT) -> str:
    """The re-briefing text: goal, topic, latest assignment, role reminder.

    A worker hears the worker reminder — edit only on the captain's
    @mention. A captain hearing that after a compaction would be told to
    disobey its own hierarchy, so a captain gets the captain-pack pointer
    instead, and its newest person message as the assignment.
    """
    conv = db.get_conversation(att["conv_id"]) or {}
    lead = bool(att.get("is_lead"))
    parts = [f"You are @{att['name']} on «{conv.get('name') or att['conv_id']}». Your context "
             "was just compacted — this re-briefing is partyline's record of your charge."]
    goal = (conv.get("goal") or "").strip()
    if goal:
        parts.append(f"Goal: {goal}")
    topic = (conv.get("topic") or "").strip()
    if topic:
        parts.append(f"Standing context (the line's topic):\n{topic}")
    assignment = latest_assignment(db, att, person_only=lead)
    if assignment:
        label = ("Latest message from a person, verbatim:" if lead
                 else "Your latest assignment, verbatim:")
        parts.append(f"{label}\n{assignment}")
    if lead:
        from .role_delivery import briefing_pointer

        parts.append(briefing_pointer(att["conv_id"]))
    else:
        parts.append(WORKER_REMINDER)
    text = "\n\n".join(parts)
    if len(text) > limit:
        text = text[:limit - 24].rstrip() + "\n… (re-briefing truncated)"
    return text
