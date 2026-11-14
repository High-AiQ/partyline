"""A task process that is waiting on a long command, not stuck.

The task server read every silent turn as a missing hand-off: one reminder,
then a `stalled` report to the root captain. An implementer waiting for a
ten-minute test run looks exactly like that from the outside — the process is
alive, its CLI sits at the prompt, and nothing is posted because nothing has
finished yet. The report was false, and it cost a captain an interruption.

Only the task process knows what it waits for, so it says so here, in a
structured call that the stall heuristic honours until it runs out. Nothing is
inferred from prose: a chat message saying "still waiting" is not a wait, and
a wait is not a stall. The wait defers the reminder and the escalation; it
never silences the task, and the line says why in one gentle note.
"""

from __future__ import annotations

import asyncio
import time

from fastapi import HTTPException

from .contracts import ConversationsChangedEvent
from .orchestrator_store import require_task, task


def live(row, now=None):
    """The declared wait, if it has not run out yet."""
    until = (row or {}).get('wait_until')
    if not until:
        return None
    if (now if now is not None else time.time()) >= until:
        return None
    return row


def note(row):
    """The gentle line note: this task process is waiting, and that is not a stall."""
    until = row.get('wait_until')
    clock = time.strftime('%H:%M', time.localtime(until)) if until else 'soon'
    role = 'reviewer' if row['status'] == 'in_review' else 'implementer'
    who = row.get(f'{role}_handle') or f'the {role}'
    return (f"⏳ waiting, not stalled: {who} is waiting on "
            f"«{row.get('wait_reason') or 'a long command'}» until {clock}; "
            'a hand-off is not due yet.')


def _declare(db, conv_id, reason, until):
    """Record the wait, then read the row back: one lock-guarded write.

    `Db` is a single connection behind `db.lock`, opened `check_same_thread=False`,
    so this is safe in a worker — and off the event loop a busy lock or a slow
    commit spends a worker's time, not the watchdog's budget.
    """
    db._exec('UPDATE task_reviews SET wait_reason=?,wait_until=? WHERE conv_id=?',
             (reason, until, conv_id))
    return task(db, conv_id)


async def waiting(runtime, actor, conv_id, body):
    """The implementer or reviewer says it is waiting on a long command."""
    db = runtime.db
    row = task(db, conv_id)
    reviewer = bool(row and row['reviewer_id'] == actor.attachment_id)
    row = require_task(db, actor, conv_id, reviewer=reviewer)
    if row['status'] not in (('in_review',) if reviewer else ('implementing', 'idle')):
        raise HTTPException(409, 'only the active implementer or reviewer can wait')
    until = time.time() + body.seconds
    row = await asyncio.to_thread(_declare, db, conv_id, body.reason, until)
    await runtime.post_message(conv_id, 'system', 'system', note(row))
    await runtime.broadcast_all(ConversationsChangedEvent())
    return row


def expired(row, now=None):
    """A wait that has run out and still says what it was waiting for."""
    until = (row or {}).get('wait_until')
    if not until:
        return None
    if (now if now is not None else time.time()) < until:
        return None
    return row


def _reset_expired(db, row):
    """Clear the expired wait — unless a newer one took its place — off the loop.

    The implementer can re-declare a wait between the orchestrator's read and
    this write, so the UPDATE matches the expired value that was read: a newer
    wait is left standing and owes no settle. `Db` is a single connection
    behind `db.lock`, opened `check_same_thread=False`, so this is safe in a
    worker — and off the event loop a busy lock or a slow commit spends a
    worker's time, not the watchdog's budget.
    """
    changed = db._exec('UPDATE task_reviews SET wait_until=NULL,stall_stage=0,stall_notice_id=NULL '
                       'WHERE conv_id=? AND wait_until=?', (row['conv_id'], row['wait_until']))
    if changed.rowcount != 1:
        return None
    role = 'reviewer_id' if row['status'] == 'in_review' else 'implementer_id'
    return db.get_attachment(row[role])


async def resume_expired(runtime, row):
    """A wait that ran out: the stall check starts over, with a fresh reminder.

    The wait deferred the reminder and the escalation. When it runs out the
    implementer owes a hand-off again, and it gets the same one reminder it
    would have had, never a skipped straight to a stall report.
    """
    if not expired(row):
        return
    if row['status'] not in ('implementing', 'idle') and not (
            row['status'] == 'in_review' and row['reviewer_id']):
        return
    role = 'reviewer_id' if row['status'] == 'in_review' else 'implementer_id'
    presence = getattr(runtime, 'presence', None)
    if presence is not None and presence.is_working(row[role]):
        return  # a tool call in flight: the hand-off is not due yet
    att = await asyncio.to_thread(_reset_expired, runtime.db, row)
    if att is None:
        return
    from .orchestrator_stall import settle
    await settle(runtime, att)
