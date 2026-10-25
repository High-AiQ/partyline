"""An implementer that is waiting on a long command, not stuck.

The task server read every silent turn as a missing hand-off: one reminder,
then a `stalled` report to the root captain. An implementer waiting for a
ten-minute test run looks exactly like that from the outside — the process is
alive, its CLI sits at the prompt, and nothing is posted because nothing has
finished yet. The report was false, and it cost a captain an interruption.

Only the implementer knows what it waits for, so it says so here, in a
structured call that the stall heuristic honours until it runs out. Nothing is
inferred from prose: a chat message saying "still waiting" is not a wait, and
a wait is not a stall. The wait defers the reminder and the escalation; it
never silences the task, and the line says why in one gentle note.
"""

from __future__ import annotations

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
    """The gentle line note: this implementer is waiting, and that is not a stall."""
    until = row.get('wait_until')
    clock = time.strftime('%H:%M', time.localtime(until)) if until else 'soon'
    who = row.get('implementer_handle') or 'the implementer'
    return (f"⏳ waiting, not stalled: {who} is waiting on "
            f"«{row.get('wait_reason') or 'a long command'}» until {clock}; "
            'a hand-off is not due yet.')


async def waiting(runtime, actor, conv_id, body):
    """The implementer says it is waiting on a long command."""
    db = runtime.db
    row = require_task(db, actor, conv_id)
    if row['status'] not in ('implementing', 'idle'):
        raise HTTPException(409, 'only an implementing task can wait')
    until = time.time() + body.seconds
    db._exec('UPDATE task_reviews SET wait_reason=?,wait_until=? WHERE conv_id=?',
             (body.reason, until, conv_id))
    await runtime.post_message(conv_id, 'system', 'system', note(task(db, conv_id)))
    await runtime.broadcast_all(ConversationsChangedEvent())
    return task(db, conv_id)


def expired(row, now=None):
    """A wait that has run out and still says what it was waiting for."""
    until = (row or {}).get('wait_until')
    if not until:
        return None
    if (now if now is not None else time.time()) < until:
        return None
    return row


async def resume_expired(runtime, row):
    """A wait that ran out: the stall check starts over, with a fresh reminder.

    The wait deferred the reminder and the escalation. When it runs out the
    implementer owes a hand-off again, and it gets the same one reminder it
    would have had, never a skipped straight to a stall report.
    """
    if not expired(row):
        return
    if row['status'] not in ('implementing', 'idle'):
        return
    presence = getattr(runtime, 'presence', None)
    if presence is not None and presence.is_working(row['implementer_id']):
        return  # a tool call in flight: the hand-off is not due yet
    db = runtime.db
    db._exec('UPDATE task_reviews SET wait_until=NULL,stall_stage=0,stall_notice_id=NULL '
             'WHERE conv_id=?', (row['conv_id'],))
    att = db.get_attachment(row['implementer_id'])
    if att is None:
        return
    from .orchestrator_stall import settle
    await settle(runtime, att)
