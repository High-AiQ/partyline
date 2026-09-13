"""A durable "mid-turn" mark, so a resumed process is told it was cut off.

Presence knows a turn is open only in memory. A deploy restart kills every
live process mid-turn and the resume brings each back with full context —
at its prompt, waiting, while the process that assigned the work waits for a
return that will never come. Two captains sat like that for a minute today
until a person noticed. So the open turn is also written to the row, and a
resume that finds the mark rings the process once: continue where you left off.
"""

from __future__ import annotations

WORKING_PHASES = ("working", "speaking")


def note_phase(db, att_id: str, phase: str) -> None:
    """Set the mark when presence announces work. Idle never clears it here:
    a process that exits mid-turn is announced idle too, and an orderly
    shutdown announced every live process idle a second before killing it —
    which wiped the very mark the resume needed. Only `ended` clears."""
    if db is not None and phase in WORKING_PHASES:
        db._exec("UPDATE attachments SET turn_open=1 WHERE id=?", (att_id,))


def was_interrupted(db, att_id: str) -> bool:
    row = db.get_attachment(att_id) or {}
    return bool(row.get("turn_open"))


def clear(db, att_id: str) -> None:
    """The harness reported the turn ended, or a resume consumed the mark."""
    if db is None:
        return
    db._exec("UPDATE attachments SET turn_open=0 WHERE id=?", (att_id,))


async def announce_if_interrupted(runtime, att: dict) -> bool:
    """Before a resume spawns: clear the mark and file the notice for that
    process alone, unrouted, so it rides the backlog the spawn is given."""
    from .mention_relay import post_private

    if not was_interrupted(runtime.db, att["id"]):
        return False
    clear(runtime.db, att["id"])  # cleared first so a failed post cannot ring twice
    await post_private(runtime, att["conv_id"], "system", "system",
                       continue_notice(att["name"]), audience=att["id"], route=False)
    return True


def continue_notice(name: str) -> str:
    return (f"↻ @{name} — your process was restarted in the middle of a turn. Nothing on "
            "disk was lost. Continue exactly where you left off, and hand off with an "
            "@mention when you are done")
