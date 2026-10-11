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


def notes_block(db, att: dict, budget: int) -> str:
    """The notebook scopes, tree first, within ``budget`` characters.

    Dropped whole-oldest-first when over budget: the process's own notes are
    the last thing a fresh context needs and the most likely to be long, but
    the tree's contracts and the line's charge are shorter and come first.
    """
    from .line_notes import read_notes, tree_root

    conv_id = att["conv_id"]
    scopes = (
        ("Tree notes (contracts, standing rules):", "tree", tree_root(db, conv_id), ""),
        ("Line notes (goal, acceptance, decisions):", "line", conv_id, ""),
        ("Your own notes:", "attachment", conv_id, att["id"]),
    )
    parts: list[str] = []
    for label, scope, store, att_id in scopes:
        text = read_notes(db, store, scope, att_id)["notes"].strip()
        if text:
            parts.append(f"{label}\n{text}")
    block = "\n\n".join(parts)
    if len(block) > budget:
        block = block[:budget - 24].rstrip() + "\n… (notes truncated)"
    return block


def render_rebrief(db, att: dict, limit: int = REBRIEF_LIMIT) -> str:
    """The re-briefing text: goal, topic, notes, latest assignment, reminder.

    A worker hears the worker reminder — edit only on the captain's
    @mention. A captain hearing that after a compaction would be told to
    disobey its own hierarchy, so a captain gets the captain-pack pointer
    instead, and its newest person message as the assignment.

    Assembled by priority, not by importance-of-place: the header, the
    assignment and the role reminder are built first and always survive; the
    notes get half of what is left; the goal and the topic share the rest and
    are truncated with a pointer to the full text. The topic alone may now be
    20,000 characters, so an end-truncate would otherwise eat exactly the
    sections the notes budget exists to protect.
    """
    conv = db.get_conversation(att["conv_id"]) or {}
    conv_id = att["conv_id"]
    lead = bool(att.get("is_lead"))
    header = (f"You are @{att['name']} on «{conv.get('name') or conv_id}». Your context "
              "was just compacted — this re-briefing is partyline's record of your charge.")
    assignment = latest_assignment(db, att, person_only=lead)
    if assignment:
        label = ("Latest message from a person, verbatim:" if lead
                 else "Your latest assignment, verbatim:")
        assignment = f"{label}\n{assignment}"
    if lead:
        from .role_delivery import briefing_pointer

        reminder = briefing_pointer(conv_id)
    else:
        reminder = WORKER_REMINDER
    fixed = [part for part in (header, assignment, reminder) if part]
    # Two more parts (context, notes) may join the join, so reserve their
    # separators up front: the budget must cover the "\n\n" between parts.
    remaining = max(0, limit - sum(len(part) for part in fixed)
                    - 2 * (len(fixed) + 1))
    notes = notes_block(db, att, remaining // 2)
    context_budget = remaining - len(notes) - (2 if notes else 0)
    pointer = f"… (full text: GET /api/conversations/{conv_id})"
    context = ""
    goal = (conv.get("goal") or "").strip()
    topic = (conv.get("topic") or "").strip()
    if goal:
        context = f"Goal: {goal}"
    if topic:
        context += ("\n\n" if context else "") + f"Standing context (the line's topic):\n{topic}"
    if context and len(context) + len(pointer) + 2 > context_budget:
        context = context[:max(0, context_budget - len(pointer) - 2)].rstrip() + "\n" + pointer
    parts = [part for part in (header, context, notes, assignment, reminder) if part]
    return "\n\n".join(parts)
