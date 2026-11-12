"""Replace a process that has compacted too often with a fresh instance of itself.

Each compaction is a lossy summary of the last, so after a few the cheapest
good move is to start over from a short, deliberate hand-off. The flow is
event-driven end to end — no timer decides anything:

1. A compaction event (`compaction_events`) counts the activation's
   compactions. At the limit, or when the thrash rule fires, the process is
   *armed*. Nothing happens mid-turn.
2. At the end of the turn that follows (`Presence.ended`, the harness receipt)
   an armed process is asked, once and privately, to write its hand-off note
   with the notes tool. That ask is a wake, so it opens one more turn.
3. At the end of the turn that has *read* the ask — or of any later one — the
   process is stopped and a fresh CLI session starts on the SAME attachment,
   briefed from the goal, its hand-off note and its latest assignment. A
   process that ignored the ask is rotated all the same.

The attachment row never changes, so the handle, preset, line, lead flag, task
role, bridge, notes and delivery cursor carry over; only the CLI session and the
runtime owner are new. A restart request or a captain handover in flight defers
the rotation to a later turn end. The one deadline is a short grace after the
receipt, because the transcript tail posts a turn's last words just after it.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shlex
import time
import uuid
from dataclasses import dataclass

from fastapi import HTTPException

from .line_notes import read_notes
from .mention_relay import live_manager, post_private

logger = logging.getLogger(__name__)
GRACE_SECONDS = 3.0
# A few thousand tokens: the 4000-character hand-off note plus the role
# briefing, the goal and the assignment.
BRIEFING_LIMIT = 12000
sleep = asyncio.sleep  # one-shot grace only; tests replace it
_TASKS: set[asyncio.Task] = set()


@dataclass
class Armed:
    owner: str
    reason: str
    count: int
    limit: int
    asked_id: int | None = None
    asked_at: float = 0.0
    scheduled: bool = False
    failures: int = 0


def armed_table(runtime) -> dict[str, Armed]:
    table = getattr(runtime, "rotations", None)
    if table is None:
        table = runtime.rotations = {}
    return table


def arm(runtime, att: dict, reason: str, count: int, limit: int) -> None:
    """Mark this activation for rotation; the first reason stands."""
    table = armed_table(runtime)
    current = table.get(att["id"])
    owner = att.get("runtime_owner") or ""
    if current is None or current.owner != owner:
        table[att["id"]] = Armed(owner, reason, count, limit)


def blocker(runtime, att: dict) -> str:
    """Why this process must not be replaced right now ('' when it may be)."""
    from .captain_handover import state_text

    if getattr(runtime, "restart_request", None) is not None:
        return "a restart request is pending"
    if getattr(runtime, "stopping", False):
        return "the server is stopping"
    if att["id"] in runtime.reattaching:
        return "it is being restored"
    if state_text(runtime.db, att["id"]):
        return "a captain handover is pending"
    return ""


def ask_text(armed: Armed) -> str:
    return (f"↻ Partyline is replacing you with a fresh instance of yourself ({armed.reason}) "
            "when this turn ends. Write your hand-off note "
            "NOW with the notes tool (scope attachment; or PUT "
            "$PARTYLINE_API/api/conversations/$PARTYLINE_CONV_ID/notes?scope=attachment): "
            "your state, decisions made, next step, and paths and SHAs, at most 4000 "
            "characters. Then end your turn. The fresh instance is briefed from that note, "
            "the goal and your latest assignment — nothing else survives.")


async def turn_ended(runtime, presence, att_id: str, owner: str | None) -> bool:
    """A turn ended. True when this process is now being rotated (skip its flush)."""
    table = armed_table(runtime)
    armed = table.get(att_id)
    if armed is None:
        return False
    att = runtime.db.get_attachment(att_id)
    if att is None or armed.owner != owner or att.get("runtime_owner") != owner:
        table.pop(att_id, None)  # a stale arm from an earlier activation
        return False
    if armed.scheduled or blocker(runtime, att):
        return armed.scheduled
    if armed.asked_id is None:
        armed.asked_at = time.time()
        copy = await post_private(runtime, att["conv_id"], "system", "system", ask_text(armed),
                                  audience=att_id)
        armed.asked_id = copy["id"]
        return False
    if att["last_seen"] < armed.asked_id:
        return False  # the ask is still queued: let this turn's flush deliver it
    armed.scheduled = True
    task = asyncio.create_task(rotate(runtime, presence, att_id, owner))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return True


async def drain() -> None:
    """Wait for every in-flight rotation — for tests and shutdown."""
    if _TASKS:
        await asyncio.gather(*_TASKS, return_exceptions=True)


async def rotate(runtime, presence, att_id: str, owner: str) -> None:
    if await attempt(runtime, presence, att_id, owner):
        return
    att = runtime.db.get_attachment(att_id)  # not rotated: wakes held at that turn end still go out
    if att and att["status"] == "running" and att_id in runtime.live and not presence.is_working(att_id):
        await presence.queue.flush(att_id, turn_ended=True)


async def attempt(runtime, presence, att_id: str, owner: str) -> bool:
    """True when this attempt is over for good (rotated, gone or given up)."""
    db = runtime.db
    armed = armed_table(runtime).get(att_id)
    if armed is None:
        return True
    await sleep(GRACE_SECONDS)  # let the tail post the turn's last words
    att = db.get_attachment(att_id)
    if (att is None or att.get("runtime_owner") != owner or att["status"] != "running"
            or att_id not in runtime.live or presence.is_working(att_id) or blocker(runtime, att)):
        armed.scheduled = False  # the next turn end looks again
        return att is None or att_id not in runtime.live or presence.is_working(att_id)
    try:
        plan = preflight(runtime, att)
    except HTTPException as exc:
        armed_table(runtime).pop(att_id, None)
        await notice(runtime, att, f"⚠ @{att['name']} was due for rotation "
                                   f"({armed.reason}) but cannot be restarted: {exc.detail}")
        return False
    if plan is None:  # a helper holds no staffed role: nothing to rotate
        armed_table(runtime).pop(att_id, None)
        return False
    note = read_notes(db, att["conv_id"], "attachment", att_id)
    wrote = bool(note["notes"].strip()) and (note["updated_at"] or 0) >= armed.asked_at
    how = ("briefed from its hand-off note" if wrote else
           "wrote no hand-off note, so it is briefed from its last note")
    runtime.reattaching.add(att_id)  # mentions queue for the fresh instance; the bridge stays
    try:
        await swap(runtime, presence, att, armed, plan, how)
    except (Exception, asyncio.CancelledError) as exc:
        logger.exception("rotation of %s failed", att_id)
        current = db.get_attachment(att_id)
        alive = bool(current and current.get("runtime_owner") == owner and current["status"] == "running")
        armed.failures += 1  # still the old process: try again at a later turn end, once
        if not alive or armed.failures >= 2:
            armed_table(runtime).pop(att_id, None)
        armed.scheduled = alive and armed.failures >= 2
        await failed(runtime, att, getattr(exc, "detail", None) or str(exc))
        if isinstance(exc, asyncio.CancelledError):
            raise
        return not alive
    finally:
        runtime.reattaching.discard(att_id)
    armed_table(runtime).pop(att_id, None)
    return True


def preflight(runtime, att: dict) -> tuple[str, str | None] | None:
    """(role, staffing preset) when the process can be restarted; raises when it cannot."""
    from . import server
    from .attachment_commands import validated_attachment_command
    from .orchestrator_store import attachment_task
    from .preset_roles import require_resume

    role = require_resume(runtime.db, att["id"])
    if role is None:
        return None
    try:
        validated_attachment_command(att["adapter"], shlex.join(att["command"]), server.ADAPTERS,
                                     server.ADAPTER_METADATA)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not os.path.isdir(att["cwd"]):
        raise HTTPException(400, "its working directory no longer exists")
    row = attachment_task(runtime.db, att["id"])
    preset = (row["policy"] if row["reviewer_id"] == att["id"] else row["implementer_preset"]) \
        if row else None
    return role, preset


async def swap(runtime, presence, att: dict, armed: Armed, plan: tuple[str, str | None], how: str) -> None:
    """Stop the process and start a new CLI session on the same attachment row."""
    from . import server
    from .attachment_broadcast import broadcast_captain
    from .line_process_routes import detach_attachment
    from .rebrief import render_rebrief
    from .resource_budget import cap_bytes, claim_resume, settings

    db, att_id = runtime.db, att["id"]
    held = presence.queue.take(att_id)  # the start's backlog delivers them; no discard notice
    # The detach line is the one public notice: who was rotated, and why.
    line = f"↻ @{att['name']} rotated to a fresh instance — {armed.reason}; {how}"
    try:
        await detach_attachment(runtime, att_id, survivors=False, expire=False,
                                source="compaction_rotation.swap", notice=line)
    except BaseException:
        presence.queue.hold(att_id, [{"id": i} for i in held])  # still the old process's wakes
        raise
    stopped = db.get_attachment(att_id)
    # A session pinned to the attachment id would be refused (or reopened), so
    # the fresh session gets an id of its own; the pin survives later resumes.
    db._exec("UPDATE attachments SET cli_session=NULL, session_pin=? WHERE id=?",
             (str(uuid.uuid4()), att_id))
    owner = str(uuid.uuid4())
    if not await claim_resume(db, att_id, owner, cap_bytes(stopped, settings(db)), grandfathered=True):
        raise HTTPException(409, "the attachment could not be claimed for its fresh instance")
    fresh = db.get_attachment(att_id)
    fresh["fresh_resume_now"] = True
    checkpoint = render_rebrief(db, fresh, limit=BRIEFING_LIMIT, handoff=True,
                                reason=f"rotated after {armed.reason}")
    role, preset = plan
    await server._start_attachment(fresh, checkpoint=checkpoint, fresh=True, staffing_role=role,
                                   staffing_preset=preset, announce=False)
    # The start delivered what is newer than the cursor, which covers what was held in
    # memory; ids the old instance persisted as skipped are delivered by this flush.
    if presence.queue.held_count(att_id) and att_id in runtime.live:
        await presence.queue.flush(att_id)
    if fresh.get("is_lead"):
        await broadcast_captain(runtime, att["conv_id"])


async def failed(runtime, att: dict, detail: str) -> None:
    body = (f"⚠ @{att['name']} rotation failed: {detail}; check the process — if it is stopped, "
            f"resume it with POST /api/attachments/{att['id']}/resume")
    await notice(runtime, att, body)
    captain = live_manager(runtime, att["conv_id"])
    if captain is not None and captain["id"] != att["id"]:
        await post_private(runtime, att["conv_id"], "system", "system", body,
                           audience=captain["id"], source=(att["id"], att["conv_id"]))


async def notice(runtime, att: dict, body: str) -> None:
    await runtime.post_message(att["conv_id"], "system", "system", body)
