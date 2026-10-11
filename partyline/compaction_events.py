"""Compaction events on a line: the counter, the notice, the thrash ring.

Finding 2.13: a worker's autocompact used to show only on its own screen.
A `PreCompact` hook event now becomes a line event — a ⚡ notice naming the
process and the count — and three auto compactions within the last five hook
turns ring the line's live captain once: that is thrash, and the remedy is a
fresh instance of the same preset, not a re-prompt.
"""

from __future__ import annotations

import time

from .contracts import MessageEvent, MessageResponse
from .mention_relay import live_manager, post_private

THRASH_AUTOS = 3
THRASH_WINDOW_TURNS = 5


def bump_turn(db, att_id: str, owner: str) -> int:
    """One more harness turn for this attachment; returns the turn number.

    A minimal db — the hook tests' fake runtime — counts nothing.
    """
    try:
        with db.lock, db.conn:
            db.conn.execute(
                "INSERT INTO hook_turns(attachment_id,runtime_owner,turns) VALUES(?,?,1) "
                "ON CONFLICT(attachment_id) DO UPDATE SET turns=CASE "
                "WHEN runtime_owner=excluded.runtime_owner THEN turns+1 ELSE 1 END, "
                "runtime_owner=excluded.runtime_owner",
                (att_id, owner))
            row = db.conn.execute(
                "SELECT turns FROM hook_turns WHERE attachment_id=?", (att_id,)).fetchone()
    except AttributeError:
        return 0
    return row["turns"]


def compaction_count(db, att_id: str) -> int:
    row = db._exec(
        "SELECT COUNT(*) AS n FROM compaction_events WHERE attachment_id=?",
        (att_id,)).fetchone()
    return row["n"] if row else 0


def compaction_counts(db) -> dict[str, int]:
    """Compaction events per attachment, for the staffing line's badge."""
    try:
        rows = db._exec(
            "SELECT attachment_id, COUNT(*) AS n FROM compaction_events "
            "GROUP BY attachment_id").fetchall()
    except AttributeError:
        return {}  # a minimal db (the staffing tests' fake) has no events
    return {row["attachment_id"]: row["n"] for row in rows}


def _ordinal(number: int) -> str:
    if 10 <= number % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    return f"{number}{suffix}"


async def note_hook_compaction(runtime, att: dict, trigger: str) -> dict:
    """One PreCompact hook event: count it, speak it, ring the captain on thrash.

    The notice is the visible record — `⚠ @<handle> compacted (auto, Nth
    time)` — posted for every compaction, auto or manual. The ring is the
    escalation: only an auto compaction that lands exactly third within the
    last five hook turns wakes the live captain, so steady compactions cost
    nobody a wake and a thrashing process costs one.
    """
    db = runtime.db
    ident, owner, conv_id = att["id"], att.get("runtime_owner") or "", att["conv_id"]
    row = db._exec("SELECT turns FROM hook_turns WHERE attachment_id=?", (ident,)).fetchone()
    turn = row["turns"] if row else 0
    with db.lock, db.conn:
        db.conn.execute(
            "INSERT INTO compaction_events"
            "(attachment_id,runtime_owner,trigger,turn,created_at) VALUES(?,?,?,?,?)",
            (ident, owner, trigger, turn, time.time()))
    # The ordinal and the thrash window are this activation's story: a fresh
    # owner starts at 1st again, and an old activation's high turn numbers
    # must not make the first compaction after a restart read as thrash. The
    # lifetime count across owners is the staffing badge's business.
    count = db._exec(
        "SELECT COUNT(*) AS n FROM compaction_events WHERE attachment_id=? "
        "AND runtime_owner=?", (ident, owner)).fetchone()["n"]
    notice = f"⚠ @{att['name']} compacted ({trigger}, {_ordinal(count)} time)"
    message = db.add_owned_message(ident, owner, conv_id, "system", "system", notice)
    if message is not None:
        await runtime.broadcast(
            conv_id, MessageEvent(message=MessageResponse.model_validate(message)))
    rung = False
    if trigger == "auto":
        window = db._exec(
            "SELECT COUNT(*) AS n FROM compaction_events WHERE attachment_id=? "
            "AND runtime_owner=? AND trigger='auto' AND turn>?",
            (ident, owner, turn - THRASH_WINDOW_TURNS)).fetchone()
        if window["n"] == THRASH_AUTOS:
            captain = live_manager(runtime, conv_id)
            if captain is not None:
                rung = True
                await post_private(
                    runtime, conv_id, "system", "system",
                    f"⚠ @{att['name']} is thrashing: {THRASH_AUTOS} auto compactions within "
                    f"the last {THRASH_WINDOW_TURNS} turns — replace it with a fresh instance "
                    "of the same preset and worktree; re-prompting will not hold",
                    audience=captain["id"], source=(ident, conv_id),
                )
    return {"notice": notice, "count": count, "thrash_ringed": rung}
