"""Compaction events on a line: the counter, the notice, the thrash ring.

Finding 2.13: a worker's autocompact used to show only on its own screen.
A `PreCompact` hook event now becomes a line event — a ⚡ notice naming the
process and the count — and three auto compactions within the last five hook
turns ring the line's live captain once: that is thrash, and the remedy is a
fresh instance of the same preset, not a re-prompt.
"""

from __future__ import annotations

import time

from .compaction_limit import limit_for
from .compaction_rotation import arm
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


def current_turns(db, att_id: str) -> int:
    """The harness turn counter for this attachment; 0 when it isn't counted.

    A minimal db — the hook tests' fake runtime — counts nothing.
    """
    try:
        row = db._exec(
            "SELECT turns FROM hook_turns WHERE attachment_id=?", (att_id,)).fetchone()
    except AttributeError:
        return 0
    return row["turns"] if row else 0


def compaction_count(db, att_id: str) -> int:
    row = db._exec(
        "SELECT epoch FROM attachment_context_epochs WHERE attachment_id=?", (att_id,)
    ).fetchone()
    epoch = row["epoch"] if row else 1
    row = db._exec(
        "SELECT COUNT(*) AS n FROM compaction_events e LEFT JOIN compaction_context_events c "
        "ON c.event_id=e.id WHERE e.attachment_id=? AND COALESCE(c.epoch,1)=?",
        (att_id, epoch)).fetchone()
    return row["n"] if row else 0


def compaction_counts(db) -> dict[str, int]:
    """Compaction events per attachment, for the staffing line's badge."""
    try:
        rows = db._exec(
            "SELECT e.attachment_id, COUNT(*) AS n FROM compaction_events e "
            "LEFT JOIN compaction_context_events c ON c.event_id=e.id "
            "LEFT JOIN attachment_context_epochs a ON a.attachment_id=e.attachment_id "
            "WHERE COALESCE(c.epoch,1)=COALESCE(a.epoch,1) GROUP BY e.attachment_id").fetchall()
    except AttributeError:
        return {}  # a minimal db (the staffing tests' fake) has no events
    return {row["attachment_id"]: row["n"] for row in rows}


def _ordinal(number: int) -> str:
    if 10 <= number % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    return f"{number}{suffix}"


async def note_transcript_compaction(runtime, att: dict, trigger: str) -> dict:
    """A compaction seen in a transcript: the hook path's events, then the rebrief.

    Claude Code gets its rebrief from the `SessionStart(compact)` hook's
    stdout; a transcript-only harness (codex, opencode-v2) has no hook whose
    stdout reaches the model, so partyline delivers the rebrief itself — a
    private wake message addressed to the compacted process, which arrives
    as its next prompt. Counting, the ⚠ notice and the thrash ring are the
    hook path's logic, unchanged; their turn window already works here
    because those adapters report turn boundaries as receipts through the
    same hook door.
    """
    from .rebrief import render_rebrief

    result = await note_hook_compaction(runtime, att, trigger)
    await post_private(
        runtime, att["conv_id"], "system", "system",
        render_rebrief(runtime.db, att),
        audience=att["id"],
    )
    return result


def transcript_compaction_callback(runtime, att: dict):
    """The adapter-side door: a transcript tail calls this when it sees one."""
    async def noted(trigger: str) -> dict:
        return await note_transcript_compaction(runtime, att, trigger or "auto")
    return noted


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
    epoch_row = db._exec(
        "SELECT epoch FROM attachment_context_epochs WHERE attachment_id=?", (ident,)
    ).fetchone()
    epoch = epoch_row["epoch"] if epoch_row else 1
    row = db._exec("SELECT turns FROM hook_turns WHERE attachment_id=?", (ident,)).fetchone()
    turn = row["turns"] if row else 0
    with db.lock, db.conn:
        event = db.conn.execute(
            "INSERT INTO compaction_events"
            "(attachment_id,runtime_owner,trigger,turn,created_at) VALUES(?,?,?,?,?)",
            (ident, owner, trigger, turn, time.time()))
        db.conn.execute(
            "INSERT INTO compaction_context_events(event_id,attachment_id,epoch) VALUES(?,?,?)",
            (event.lastrowid, ident, epoch))
    # The ordinal follows the context epoch across resumed activations. The
    # thrash window remains activation-scoped: old turn numbers after restart
    # must not make the first compaction in this activation read as thrash.
    count = db._exec(
        "SELECT COUNT(*) AS n FROM compaction_events e LEFT JOIN compaction_context_events c "
        "ON c.event_id=e.id WHERE e.attachment_id=? AND COALESCE(c.epoch,1)=?",
        (ident, epoch)).fetchone()["n"]
    notice = f"⚠ @{att['name']} compacted ({trigger}, {_ordinal(count)} time)"
    message = db.add_owned_message(ident, owner, conv_id, "system", "system", notice)
    if message is not None:
        await runtime.broadcast(
            conv_id, MessageEvent(message=MessageResponse.model_validate(message)))
    rung = False
    limit = limit_for(db, att)
    if limit and count >= limit:
        arm(runtime, att, f"{count} compactions, limit {limit}", count, limit)
    if trigger == "auto":
        window = db._exec(
            "SELECT COUNT(*) AS n FROM compaction_events WHERE attachment_id=? "
            "AND runtime_owner=? AND trigger='auto' AND turn>?",
            (ident, owner, turn - THRASH_WINDOW_TURNS)).fetchone()
        if window["n"] == THRASH_AUTOS:
            if limit:  # rotation replaces it at turn end; the captain need not act
                arm(runtime, att, f"thrashing: {THRASH_AUTOS} auto compactions within "
                    f"{THRASH_WINDOW_TURNS} turns", count, limit)
            captain = live_manager(runtime, conv_id)
            if captain is not None and not limit:
                rung = True
                await post_private(
                    runtime, conv_id, "system", "system",
                    f"⚠ @{att['name']} is thrashing: {THRASH_AUTOS} auto compactions within "
                    f"the last {THRASH_WINDOW_TURNS} turns — replace it with a fresh instance "
                    "of the same preset and worktree; re-prompting will not hold. "
                    f"Replace it: POST /api/attachments/{ident}/replace",
                    audience=captain["id"], source=(ident, conv_id),
                )
    return {"notice": notice, "count": count, "thrash_ringed": rung}
