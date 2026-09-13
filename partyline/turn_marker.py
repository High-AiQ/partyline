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
    """Record whether a turn is open, from the phase presence just announced."""
    if db is None:
        return
    db._exec("UPDATE attachments SET turn_open=? WHERE id=?",
             (1 if phase in WORKING_PHASES else 0, att_id))


def was_interrupted(db, att_id: str) -> bool:
    row = db.get_attachment(att_id) or {}
    return bool(row.get("turn_open"))


def clear(db, att_id: str) -> None:
    db._exec("UPDATE attachments SET turn_open=0 WHERE id=?", (att_id,))


def continue_notice(name: str) -> str:
    return (f"↻ @{name} — your process was restarted in the middle of a turn. Nothing on "
            "disk was lost. Continue exactly where you left off, and hand off with an "
            "@mention when you are done")
